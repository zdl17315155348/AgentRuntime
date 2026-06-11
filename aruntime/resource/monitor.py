"""
资源监控器
基于 psutil 采集系统 CPU/内存以及 LLM 并发数，为资源感知调度提供决策依据
"""

import os
import psutil
from typing import Dict, Set


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
        self._active_llm_agents: Set[str] = set()
        self._agent_llm_counts: Dict[str, int] = {}

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

    def acquire_llm(self, agent_name: str, llm_max_concurrent: int = 1) -> bool:
        """尝试申请 LLM 资源。成功返回 True，失败返回 False"""
        current = self._agent_llm_counts.get(agent_name, 0)
        if current >= llm_max_concurrent:
            return False
        if len(self._active_llm_agents) >= self.llm_max_concurrent and agent_name not in self._active_llm_agents:
            return False
        self._active_llm_agents.add(agent_name)
        self._agent_llm_counts[agent_name] = current + 1
        return True

    def release_llm(self, agent_name: str) -> None:
        """释放 LLM 资源"""
        current = self._agent_llm_counts.get(agent_name, 0)
        if current <= 1:
            self._active_llm_agents.discard(agent_name)
            self._agent_llm_counts.pop(agent_name, None)
        else:
            self._agent_llm_counts[agent_name] = current - 1

    # ---- 快照 ----

    def get_snapshot(self) -> dict:
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "mem_percent": psutil.virtual_memory().percent,
            "mem_available_mb": round(psutil.virtual_memory().available / (1024 * 1024), 1),
            "llm_active_agents": list(self._active_llm_agents),
            "llm_total_concurrent": sum(self._agent_llm_counts.values()),
            "llm_max_concurrent": self.llm_max_concurrent,
        }

    # ---- 内部检查 ----

    def _check_system_cpu(self) -> bool:
        return psutil.cpu_percent(interval=0.1) < self.cpu_threshold

    def _check_system_memory(self) -> bool:
        return psutil.virtual_memory().percent < self.mem_threshold

    def _check_llm_global(self) -> bool:
        return len(self._active_llm_agents) < self.llm_max_concurrent
