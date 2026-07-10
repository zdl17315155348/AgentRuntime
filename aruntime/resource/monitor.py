"""
资源监控器
基于 psutil 采集系统 CPU/内存以及 LLM 并发数，为资源感知调度提供决策依据
"""

import asyncio
import os
import psutil
from typing import Dict, Set

from aruntime.resource.types import (
    ResourceClass,
    ResourceLease,
    ResourceQuota,
    ResourceReclaimer,
    ResourceRequest,
    ResourceUsage,
)


class ResourceMonitor:
    """系统资源监控器 + LLM 并发追踪"""

    def __init__(
        self,
        cpu_threshold: float | None = None,
        mem_threshold: float | None = None,
        llm_max_concurrent: int | None = None,
    ):
        self.cpu_threshold = cpu_threshold or float(os.getenv("RESOURCE_CPU_THRESHOLD", "80"))
        self.mem_threshold = mem_threshold or float(os.getenv("RESOURCE_MEM_THRESHOLD", "80"))
        self.llm_max_concurrent = llm_max_concurrent or int(os.getenv("RESOURCE_LLM_MAX_CONCURRENT", "5"))
        self.quota = ResourceQuota(limits={
            ResourceClass.CPU: 100.0,
            ResourceClass.MEMORY: float(os.getenv("RESOURCE_MEMORY_QUOTA_BYTES", "0") or 0),
            ResourceClass.LLM_CONCURRENCY: float(self.llm_max_concurrent),
            ResourceClass.TOKEN: float(os.getenv("RESOURCE_TOKEN_QUOTA", "0") or 0),
            ResourceClass.TOOL: float(os.getenv("RESOURCE_TOOL_QUOTA", "0") or 0),
            ResourceClass.KV_CACHE: float(os.getenv("RESOURCE_KV_CACHE_QUOTA", "0") or 0),
            ResourceClass.NETWORK: float(os.getenv("RESOURCE_NETWORK_QUOTA", "0") or 0),
        })
        self.usage = ResourceUsage()
        self.reclaimer = ResourceReclaimer()
        self._leases: Dict[str, ResourceLease] = {}
        self._task_leases: Dict[str, str] = {}
        self._active_llm_agents: Set[str] = set()
        self._agent_llm_counts: Dict[str, int] = {}
        self._llm_total_concurrent = 0
        self._lock = asyncio.Lock()

    # ---- 核心决策方法 ----

    def has_enough(self, memory_max_bytes: int | None = None, cpu_max: str | None = None,
                   llm_max_concurrent: int = 1) -> bool:
        """
        判断当前系统资源是否足够调度一个 Agent 执行。

        检查项：
        1. 系统 CPU 使用率 <= threshold
        2. 系统内存使用率 <= threshold
        3. 全局 LLM 并发数 < 上限
        """
        if not self._check_system_cpu():
            return False
        if not self._check_system_memory():
            return False
        if not self._check_llm_global():
            return False
        return True

    def acquire(self, task_id: str, agent_name: str, request: ResourceRequest | dict | None = None) -> ResourceLease | None:
        if not isinstance(request, ResourceRequest):
            request = ResourceRequest.from_dict(request or {})
        if not request.amounts:
            lease = ResourceLease(task_id=task_id, agent_name=agent_name, request=request)
            self._leases[lease.lease_id] = lease
            self._task_leases[task_id] = lease.lease_id
            return lease
        ok, _ = self.can_allocate(request)
        if not ok:
            return None
        llm_amount = int(request.get(ResourceClass.LLM_CONCURRENCY, 0) or 0)
        per_agent_limit = max(llm_amount, 1)
        if self._agent_llm_counts.get(agent_name, 0) + llm_amount > per_agent_limit:
            return None
        if self._llm_total_concurrent + llm_amount > self.llm_max_concurrent:
            return None
        lease = ResourceLease(task_id=task_id, agent_name=agent_name, request=request)
        self._leases[lease.lease_id] = lease
        self._task_leases[task_id] = lease.lease_id
        for resource_class, amount in request.amounts.items():
            self.usage.add(resource_class, amount)
        for _ in range(llm_amount):
            self.acquire_llm(agent_name)
        return lease

    async def acquire_async(self, task_id: str, agent_name: str, request: ResourceRequest | dict | None = None) -> ResourceLease | None:
        async with self._lock:
            return self.acquire(task_id, agent_name, request)

    def release(self, lease_or_task_id: ResourceLease | str | None) -> None:
        if lease_or_task_id is None:
            return
        lease = lease_or_task_id
        if isinstance(lease_or_task_id, str):
            lease_id = self._task_leases.get(lease_or_task_id, lease_or_task_id)
            lease = self._leases.get(lease_id)
        if lease is None or lease.status != "active":
            return
        for resource_class, amount in lease.request.amounts.items():
            self.usage.sub(resource_class, amount)
        llm_amount = int(lease.request.get(ResourceClass.LLM_CONCURRENCY, 0) or 0)
        for _ in range(llm_amount):
            self.release_llm(lease.agent_name)
        lease.release()
        self._task_leases.pop(lease.task_id, None)

    async def release_async(self, lease_or_task_id: ResourceLease | str | None) -> None:
        async with self._lock:
            self.release(lease_or_task_id)

    def reclaim(self, task_id: str, reason: str = "") -> None:
        lease_id = self._task_leases.get(task_id)
        lease = self._leases.get(lease_id or "")
        if lease is None:
            return
        self.release(lease)
        self.reclaimer.reclaim(lease, reason=reason)

    async def reclaim_async(self, task_id: str, reason: str = "") -> None:
        async with self._lock:
            self.reclaim(task_id, reason=reason)

    def can_allocate(self, request: ResourceRequest) -> tuple[bool, str]:
        if request.get(ResourceClass.CPU) > 0 and not self._check_system_cpu():
            return False, "cpu_threshold"
        if request.get(ResourceClass.MEMORY) > 0 and not self._check_system_memory():
            return False, "memory_threshold"
        for resource_class, amount in request.amounts.items():
            quota = self.quota.get(resource_class)
            if quota <= 0:
                continue
            if self.usage.get(resource_class) + amount > quota:
                return False, f"{resource_class.value}_quota"
        return True, "resource_available"

    def monitor_lease(self, lease: ResourceLease) -> tuple[bool, str]:
        if not lease.request.amounts:
            return True, "within_limits"
        ok, reason = self.can_allocate(ResourceRequest())
        if not ok:
            return False, reason
        for resource_class, amount in lease.request.amounts.items():
            quota = self.quota.get(resource_class)
            if quota > 0 and amount > quota:
                return False, f"{resource_class.value}_lease_limit"
        return True, "within_limits"

    def acquire_llm(self, agent_name: str, llm_max_concurrent: int = 1) -> bool:
        """尝试申请 LLM 资源。成功返回 True，失败返回 False"""
        current = self._agent_llm_counts.get(agent_name, 0)
        if current >= llm_max_concurrent:
            return False
        if self._llm_total_concurrent >= self.llm_max_concurrent:
            return False
        self._active_llm_agents.add(agent_name)
        self._agent_llm_counts[agent_name] = current + 1
        self._llm_total_concurrent += 1
        return True

    def release_llm(self, agent_name: str) -> None:
        """释放 LLM 资源"""
        current = self._agent_llm_counts.get(agent_name, 0)
        if current <= 1:
            self._active_llm_agents.discard(agent_name)
            self._agent_llm_counts.pop(agent_name, None)
        else:
            self._agent_llm_counts[agent_name] = current - 1
        self._llm_total_concurrent = max(self._llm_total_concurrent - 1, 0)

    # ---- 快照 ----

    def get_snapshot(self) -> dict:
        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "mem_percent": psutil.virtual_memory().percent,
            "mem_available_mb": round(psutil.virtual_memory().available / (1024 * 1024), 1),
            "llm_active_agents": list(self._active_llm_agents),
            "llm_total_concurrent": self._llm_total_concurrent,
            "llm_max_concurrent": self.llm_max_concurrent,
            "usage": self.usage.to_dict(),
            "leases": [lease.to_dict() for lease in self._leases.values() if lease.status == "active"],
            "reclaimed": [lease.to_dict() for lease in self.reclaimer.reclaimed],
        }

    # ---- 内部检查 ----

    def _check_system_cpu(self) -> bool:
        return psutil.cpu_percent(interval=None) < self.cpu_threshold

    def _check_system_memory(self) -> bool:
        return psutil.virtual_memory().percent < self.mem_threshold

    def _check_llm_global(self) -> bool:
        return self._llm_total_concurrent < self.llm_max_concurrent
