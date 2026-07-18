"""agentd 守护进程 - 接收请求，模拟执行任务"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional
import subprocess
import secrets
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from aruntime.core.acb import AgentControlBlock
from aruntime.core.models import AgentCapability, AgentSpec, FailurePolicy, FailureMode, SideEffectLevel, TaskAttempt, TaskSpec, TaskStatus, AgentStatus
from aruntime.core.lifecycle import transition_to, InvalidTransitionError
from aruntime.scheduler.fifo import FIFOScheduler
from aruntime.scheduler.dag import DAGScheduler
from aruntime.scheduler.kernel import KernelScheduler
from aruntime.scheduler.base import BaseScheduler
import os
from aruntime.llm.gateway import LLMGateway
from aruntime.comm.message import Message
from aruntime.comm.router import MessageRouter
from aruntime.comm.transport import start_uds_server
from aruntime.context.manager import ContextManager
from aruntime.resource.cgroup import CgroupManager, apply_cgroup_v2
from aruntime.resource.monitor import ResourceMonitor
from aruntime.resource.types import ResourceClass, ResourceLease, ResourceRequest
from aruntime.scheduler.resource_aware import ResourceAwareScheduler
from aruntime.observability import TraceRecorder
from aruntime.daemon.fault_service import WorkerFaultState, retry_backoff_seconds
from aruntime.daemon.recovery_service import recover_tasks
from aruntime.daemon.store import SQLiteStateStore
from aruntime.daemon.worker_service import json_log, start_worker_process

import json

# 配置路径：优先使用环境变量指定的路径，默认从项目根目录的 configs/ 下加载
CONFIG_PATH = os.getenv("RUNTIME_CONFIG", 
    os.path.join(os.path.dirname(__file__), "..", "..", "configs", "runtime.json"))


def load_config():
    """加载 JSON 配置文件"""
    config_path = CONFIG_PATH
    if not os.path.exists(config_path):
        # 如果配置文件不存在，使用默认配置（mock 模式）
        return {
            "llm": {
                "backend": "mock",
                "api_key": "",
                "model": "deepseek-chat",
                "temperature": 0.1,
                "max_tokens": 2048
            }
        }
    with open(config_path, "r") as f:
        return json.load(f)


# 加载配置
config = load_config()
llm_config = config.get("llm", {})
scheduler_config = config.get("scheduler", {})
context_config = config.get("context", {})
if not isinstance(context_config, dict):
    context_config = {}


def _context_compress_threshold() -> int:
    try:
        value = int(context_config.get("compress_threshold_chars", 4000))
    except (TypeError, ValueError):
        return 4000
    return value if value > 0 else 4000

# 初始化 LLM 网关
LLM_BACKEND = os.getenv("LLM_BACKEND", llm_config.get("backend", "deepseek"))
LLM_API_KEY = os.getenv("LLM_API_KEY", llm_config.get("api_key", ""))
llm_gateway = LLMGateway(backend=LLM_BACKEND, api_key=LLM_API_KEY)
context_manager = ContextManager(
    compress_threshold_chars=_context_compress_threshold()
)

agents: Dict[str, AgentSpec] = {}
agent_controls: Dict[str, AgentControlBlock] = {}
tasks: Dict[str, TaskSpec] = {}

# 初始化调度器
SCHEDULER_TYPE = os.getenv("SCHEDULER_TYPE", scheduler_config.get("type", "fifo"))
SCHEDULER_POLICY = os.getenv("SCHEDULER_POLICY", scheduler_config.get("policy", "priority"))
resource_aware = os.getenv("RESOURCE_AWARE", "").lower() in ("true", "1", "yes") or scheduler_config.get("resource_aware", False)
resource_monitor: ResourceMonitor = ResourceMonitor()
cgroup_strict = os.getenv("CGROUP_STRICT", "").lower() in ("true", "1", "yes")
cgroup_manager = CgroupManager()


def _resource_request_for_task(task: TaskSpec, agent: AgentSpec) -> ResourceRequest:
    raw = dict(task.resource_request or {})
    if agent.memory_max_bytes:
        raw.setdefault(ResourceClass.MEMORY.value, float(agent.memory_max_bytes))
    if task.token_budget:
        raw.setdefault(ResourceClass.TOKEN.value, float(task.token_budget))
    return ResourceRequest.from_dict(raw)


def _cgroup_ready(agent_name: str) -> tuple[bool, str]:
    if not cgroup_strict:
        return True, "cgroup_not_strict"
    binding = cgroup_bindings.get(agent_name)
    if binding and binding.get("ok") is True:
        return True, "cgroup_ready"
    return False, "cgroup_bind_failed"


def _kernel_resource_checker(task: TaskSpec) -> tuple[bool, str]:
    agent = agents.get(task.agent_name)
    if agent is None:
        return False, "agent_missing"
    ok, reason = _cgroup_ready(task.agent_name)
    if not ok:
        return ok, reason
    ok, reason = resource_monitor.can_allocate(_resource_request_for_task(task, agent))
    return ok, reason

if SCHEDULER_TYPE == "kernel":
    _inner: BaseScheduler = KernelScheduler(
        policy=SCHEDULER_POLICY,
        resource_checker=_kernel_resource_checker if resource_monitor is not None else None,
        agent_provider=lambda: list(agents.values()),
    )
elif SCHEDULER_TYPE in ("fifo", "priority", "resource_aware", "fair_share", "deadline"):
    policy = "resource_aware" if SCHEDULER_TYPE == "resource_aware" else SCHEDULER_TYPE
    _inner: BaseScheduler = KernelScheduler(
        policy=policy,
        resource_checker=_kernel_resource_checker if resource_monitor is not None else None,
        agent_provider=lambda: list(agents.values()),
    )
elif SCHEDULER_TYPE == "dag":
    _inner: BaseScheduler = DAGScheduler()
else:
    _inner: BaseScheduler = FIFOScheduler()

if resource_aware and not isinstance(_inner, KernelScheduler):
    scheduler: BaseScheduler = ResourceAwareScheduler(_inner, resource_monitor, agents)
else:
    scheduler: BaseScheduler = _inner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentd")

state_store = SQLiteStateStore()
agent_inflight_tasks: Dict[str, int] = {}
agent_auth_tokens: Dict[str, str] = {}
fault_states: Dict[str, WorkerFaultState] = {}
message_router = MessageRouter(store=state_store)
cgroup_bindings: Dict[str, dict] = {}
uds_server = None
agent_workers: Dict[str, subprocess.Popen] = {}
pending_task_results: Dict[str, dict] = {}
trace_recorder = TraceRecorder()
scheduler_event: asyncio.Event | None = None
global_dispatch_semaphore: asyncio.Semaphore | None = None
agent_dispatch_semaphores: Dict[str, asyncio.Semaphore] = {}
llm_usage_totals = {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
    "latency_ms_total": 0.0,
    "calls": 0,
    "prefix_cache_hits": 0,
    "logical_context_reuse_hits": 0,
}

app = FastAPI(title="Agent Runtime Daemon", version="0.1.0")


def _persist_agent(agent_name: str) -> None:
    agent = agents.get(agent_name)
    if agent is None:
        return
    proc = agent_workers.get(agent_name)
    fault = fault_states.get(agent_name)
    state_store.save_agent(
        agent,
        worker_pid=(proc.pid if proc is not None else None),
        auth_token=agent_auth_tokens.get(agent_name, ""),
        last_heartbeat=(fault.last_heartbeat if fault else None),
    )


def _persist_task(task: TaskSpec | None) -> None:
    if task is not None:
        state_store.save_task(task)


def _sync_agent_from_acb(agent_name: str) -> None:
    agent = agents.get(agent_name)
    acb = agent_controls.get(agent_name)
    if agent is None or acb is None:
        return
    agent.status = acb.status
    agent.current_task_id = acb.current_task_id
    agent.updated_at = acb.updated_at


def _transition_agent(
    agent_name: str,
    new_status: AgentStatus,
    task_id: str | None = None,
    reason: str = "",
) -> None:
    acb = agent_controls.get(agent_name)
    if acb is not None:
        transition_to(acb, new_status, task_id=task_id, reason=reason)
        _sync_agent_from_acb(agent_name)
        _persist_agent(agent_name)
        return
    agent = agents[agent_name]
    transition_to(agent, new_status, task_id=task_id, reason=reason)
    _persist_agent(agent_name)


def _recover_agent(agent_name: str, task_id: str | None = None, reason: str = "agent.recover") -> None:
    agent = agents.get(agent_name)
    if agent is None:
        return
    if agent.status == AgentStatus.FAILED:
        _transition_agent(agent_name, AgentStatus.RECOVERING, task_id=task_id, reason=f"{reason}.start")
        _transition_agent(agent_name, AgentStatus.READY, task_id=task_id, reason=f"{reason}.ready")


def _set_current_task(agent_name: str, task_id: str | None) -> None:
    acb = agent_controls.get(agent_name)
    if acb is not None:
        acb.set_current_task(task_id)
    agent = agents.get(agent_name)
    if agent is not None:
        agent.current_task_id = task_id
        _persist_agent(agent_name)


def _set_context_handle(agent_name: str, context_id: str | None) -> None:
    acb = agent_controls.get(agent_name)
    if acb is not None:
        acb.set_context(context_id)


def _wake_scheduler() -> None:
    if scheduler_event is not None:
        scheduler_event.set()


def _agent_semaphore(agent_name: str) -> asyncio.Semaphore:
    agent = agents.get(agent_name)
    limit = max(int(agent.llm_max_concurrent if agent else 1), 1)
    sem = agent_dispatch_semaphores.get(agent_name)
    if sem is None:
        sem = asyncio.Semaphore(limit)
        agent_dispatch_semaphores[agent_name] = sem
    return sem


def _start_worker(agent_name: str) -> subprocess.Popen:
    uds_path = os.getenv("AGENTD_UDS_PATH", "/tmp/agent-runtime-agentd.sock")
    token = agent_auth_tokens.setdefault(agent_name, secrets.token_urlsafe(24))
    workspace_root = os.getenv("AGENT_WORKSPACE", "")
    proc = start_worker_process(agent_name, uds_path, llm_gateway.backend, llm_gateway.api_key or "", token, workspace_root or None)
    agent_workers[agent_name] = proc
    fault_states.setdefault(agent_name, WorkerFaultState(agent_name=agent_name, fault_domain=agent_name)).heartbeat()
    acb = agent_controls.get(agent_name)
    if acb is not None:
        acb.ipc_endpoint = uds_path
        acb.mailbox = agent_name
        acb.record_event("worker.started", detail={"pid": proc.pid})
    agent = agents.get(agent_name)
    if agent is not None:
        cg = apply_cgroup_v2(
            pid=proc.pid,
            group_name=agent_name,
            memory_max_bytes=agent.memory_max_bytes,
            memory_high_bytes=agent.memory_high_bytes,
            cpu_max=agent.cpu_max,
            pids_max=agent.pids_max or 64,
        )
        cgroup_bindings[agent_name] = cg
        if cg.get("ok") is not True:
            if cg.get("error"):
                logger.info(f"cgroup 未生效: {cg.get('error')}")
            if cgroup_strict:
                _stop_worker(agent_name, cleanup_cgroup=False)
                raise RuntimeError(f"cgroup bind failed: {cg.get('error') or 'unknown'}")
        _persist_agent(agent_name)
    return proc


def _stop_worker(agent_name: str, cleanup_cgroup: bool = True) -> None:
    proc = agent_workers.get(agent_name)
    if proc is not None:
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass
        agent_workers.pop(agent_name, None)
    if cleanup_cgroup:
        binding = cgroup_bindings.pop(agent_name, None)
        if binding and binding.get("ok") is True:
            cleaned = cgroup_manager.cleanup(agent_name)
            if cleaned.get("ok") is not True and cleaned.get("error"):
                logger.info(f"cgroup 清理失败: {cleaned.get('error')}")
    _persist_agent(agent_name)


def _isolate_failed_worker(agent_name: str, task_id: str, error: str) -> None:
    agent = agents.get(agent_name)
    if agent is None:
        return
    if agent.status not in (AgentStatus.FAILED, AgentStatus.KILLED):
        try:
            _transition_agent(agent_name, AgentStatus.FAILED, task_id=task_id, reason="worker.failed")
        except InvalidTransitionError:
            agent.status = AgentStatus.FAILED
    acb = agent_controls.get(agent_name)
    if acb is not None:
        acb.record_event("worker.isolated", task_id=task_id, reason="worker.failed", detail={"error": error})
    resource_monitor.reclaim(task_id, reason=error)
    state_store.release_leases_for_task(task_id, reason=error)
    _stop_worker(agent_name)
    fault = fault_states.setdefault(agent_name, WorkerFaultState(agent_name=agent_name, fault_domain=agent_name))
    if agent.status != AgentStatus.KILLED and fault.can_restart():
        fault.record_restart()
        _start_worker(agent_name)
    _persist_agent(agent_name)


def _prepare_fallback_attempt(task: TaskSpec, fallback_agent: str) -> TaskAttempt | None:
    if fallback_agent not in agents:
        task.error = f"fallback agent '{fallback_agent}' not found"
        return None
    test_cfg = task.task_input.get("__test")
    if isinstance(test_cfg, dict):
        test_cfg.pop("crash_worker", None)
    attempt = task.create_attempt(
        fallback_agent,
        worker_pid=(agent_workers.get(fallback_agent).pid if fallback_agent in agent_workers else None),
    )
    task.scheduler_decision_reason = f"fallback:{task.agent_name}->{fallback_agent}"
    agent_inflight_tasks[fallback_agent] = agent_inflight_tasks.get(fallback_agent, 0) + 1
    fault_states.setdefault(task.agent_name, WorkerFaultState(agent_name=task.agent_name, fault_domain=task.agent_name)).record_fallback(
        task.task_id,
        task.agent_name,
        fallback_agent,
        attempt.attempt_id,
    )
    _persist_task(task)
    return attempt


def _prepare_agent_for_task(task: TaskSpec, reason: str) -> None:
    agent = agents.get(task.agent_name)
    if agent is None:
        return
    if agent.status == AgentStatus.FAILED:
        _recover_agent(task.agent_name, task.task_id, reason=f"{reason}.recover")
    elif agent.status == AgentStatus.COMPLETED:
        agent.status = AgentStatus.READY
        acb = agent_controls.get(task.agent_name)
        if acb is not None:
            acb.status = AgentStatus.READY
            acb.record_event("agent.reused", task_id=task.task_id, reason=reason)
        _persist_agent(task.agent_name)
    _set_context_handle(task.agent_name, task.context_id or None)
    _transition_agent(task.agent_name, AgentStatus.RUNNING, task_id=task.task_id, reason=reason)
    _set_current_task(task.agent_name, task.task_id)


class CreateAgentRequest(BaseModel):
    agent_name: str
    role: str
    system_prompt: str = ""
    model: str = "gpt-4o-mini"
    capability: AgentCapability = Field(default_factory=AgentCapability)
    max_retries: int = 3
    restart_budget: int = 3
    fault_domain: str = ""
    memory_max_bytes: int | None = None
    memory_high_bytes: int | None = None
    cpu_max: str = ""
    pids_max: int | None = None

class SubmitTaskRequest(BaseModel):
    agent_name: str | None = None
    task_input: dict
    context_id: str = ""
    priority: int = 0
    deadline: Optional[datetime] = None
    resource_request: dict = Field(default_factory=dict)
    required_capability: dict = Field(default_factory=dict)
    token_budget: Optional[int] = None
    timeout: Optional[float] = None
    timeout_ms: Optional[int] = None
    parent_task_id: str = ""
    children: list[str] = Field(default_factory=list)
    trace_id: str = ""
    dependencies: list[str] = Field(default_factory=list)
    dependency_failure_policies: dict[str, FailureMode] = Field(default_factory=dict)
    on_failure: dict[str, FailureMode] = Field(default_factory=dict)
    failure_policy: FailurePolicy = Field(default_factory=FailurePolicy)
    idempotency_key: str | None = None
    side_effect_level: SideEffectLevel = SideEffectLevel.NONE
    compensation: dict = Field(default_factory=dict)

    @field_validator("failure_policy", mode="before")
    @classmethod
    def normalize_failure_policy(cls, value):
        return FailurePolicy.from_legacy(value)

    @field_validator("dependency_failure_policies", "on_failure", mode="before")
    @classmethod
    def normalize_edge_failure_policy(cls, value):
        if not value:
            return {}
        return {
            str(dep_id): FailureMode(mode.value if isinstance(mode, FailureMode) else str(mode).replace("-", "_"))
            for dep_id, mode in dict(value).items()
        }


class SubmitDynamicTaskRequest(BaseModel):
    agent_name: str | None = None
    task_input: dict
    parent_task_id: str = ""
    context_id: str = ""
    priority: int = 0
    deadline: Optional[datetime] = None
    resource_request: dict = Field(default_factory=dict)
    required_capability: dict = Field(default_factory=dict)
    token_budget: Optional[int] = None
    timeout: Optional[float] = None
    timeout_ms: Optional[int] = None
    trace_id: str = ""
    dependency_failure_policies: dict[str, FailureMode] = Field(default_factory=dict)
    on_failure: dict[str, FailureMode] = Field(default_factory=dict)
    failure_policy: FailurePolicy = Field(default_factory=FailurePolicy)
    idempotency_key: str | None = None
    side_effect_level: SideEffectLevel = SideEffectLevel.NONE
    compensation: dict = Field(default_factory=dict)
    inherit_context: bool = True

    @field_validator("failure_policy", mode="before")
    @classmethod
    def normalize_failure_policy(cls, value):
        return FailurePolicy.from_legacy(value)

    @field_validator("dependency_failure_policies", "on_failure", mode="before")
    @classmethod
    def normalize_edge_failure_policy(cls, value):
        if not value:
            return {}
        return {
            str(dep_id): FailureMode(mode.value if isinstance(mode, FailureMode) else str(mode).replace("-", "_"))
            for dep_id, mode in dict(value).items()
        }


class SendMessageRequest(BaseModel):
    from_agent: str
    to_agent: str
    payload: dict
    topic: str = ""


class SpawnTaskRequest(BaseModel):
    task_input: dict
    agent_name: str | None = None
    required_capability: dict = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    priority: int = 0
    resource_request: dict = Field(default_factory=dict)
    inherit_context: bool = True
    context_id: str = ""
    timeout_ms: Optional[int] = None
    failure_policy: FailurePolicy = Field(default_factory=FailurePolicy)
    dependency_failure_policies: dict[str, FailureMode] = Field(default_factory=dict)
    on_failure: dict[str, FailureMode] = Field(default_factory=dict)

    @field_validator("failure_policy", mode="before")
    @classmethod
    def normalize_failure_policy(cls, value):
        return FailurePolicy.from_legacy(value)

    @field_validator("dependency_failure_policies", "on_failure", mode="before")
    @classmethod
    def normalize_edge_failure_policy(cls, value):
        if not value:
            return {}
        return {
            str(dep_id): FailureMode(mode.value if isinstance(mode, FailureMode) else str(mode).replace("-", "_"))
            for dep_id, mode in dict(value).items()
        }


def _record_task_context(context_id: str, agent_name: str, task_input: dict) -> None:
    if not context_id:
        return
    context = task_input.get("context", {})
    if not isinstance(context, dict):
        context = {}
    shared_data = context.get("shared", {})
    private_data = context.get("private", {})
    readonly_data = context.get("readonly", context.get("readonly_context", {}))
    if not isinstance(shared_data, dict):
        shared_data = {}
    if not isinstance(private_data, dict):
        private_data = {}
    if not isinstance(readonly_data, dict):
        readonly_data = {}
    context_manager.record_task_context(context_id, agent_name, shared_data, private_data, readonly_data)


def _record_trace_event(task: TaskSpec, name: str, detail: dict | None = None) -> None:
    trace_recorder.event(task.trace_id, task.task_id, name, detail or {})
    state_store.save_trace_event(task.trace_id, task.task_id, name, detail or {})


def _attempt_agent(task: TaskSpec, attempt: TaskAttempt | None = None) -> str:
    return attempt.agent_name if attempt is not None else task.agent_name


def _make_task(**kwargs) -> TaskSpec:
    trace_id = kwargs.pop("trace_id", "")
    if trace_id:
        kwargs["trace_id"] = trace_id
    explicit_fields = kwargs.pop("_explicit_fields", set())
    if "failure_policy" not in explicit_fields:
        kwargs.pop("failure_policy", None)
    return TaskSpec(**kwargs)


def _edge_failure_policies(req) -> dict[str, FailureMode]:
    result = dict(getattr(req, "dependency_failure_policies", {}) or {})
    result.update(getattr(req, "on_failure", {}) or {})
    return result


def _explicit_fields(req) -> set[str]:
    return set(getattr(req, "model_fields_set", set()))


def _select_agent_name(agent_name: str | None, required_capability: dict | None) -> str | None:
    if agent_name:
        return agent_name
    if not required_capability:
        return None
    req = required_capability or {}
    matched: list[AgentSpec] = []
    for agent in agents.values():
        cap = agent.capability
        if req.get("can_plan") and not cap.can_plan:
            continue
        if req.get("can_code") and not cap.can_code:
            continue
        if req.get("can_test") and not cap.can_test:
            continue
        if req.get("can_review") and not cap.can_review:
            continue
        if req.get("language") and req["language"] not in cap.languages:
            continue
        if req.get("tool") and req["tool"] not in cap.tools:
            continue
        matched.append(agent)
    if matched:
        matched.sort(key=lambda item: (-float(item.capability.reliability_score), int(item.capability.cost_level), item.agent_name))
        return matched[0].agent_name
    target = scheduler._inner if hasattr(scheduler, "_inner") else scheduler
    if hasattr(target, "match_agent"):
        probe = TaskSpec(agent_name=None, task_input={}, required_capability=required_capability or {})
        selected = target.match_agent(probe, list(agents.values()))
        return selected.agent_name if selected is not None else None
    return None


def _scheduler_metrics() -> dict:
    all_tasks = list(tasks.values())
    queue_wait = [t.queue_wait_ms for t in all_tasks if t.queue_wait_ms is not None]
    runtime = [t.agent_runtime_ms for t in all_tasks if t.agent_runtime_ms is not None]
    target = scheduler._inner if hasattr(scheduler, "_inner") else scheduler
    queues = target.queue_snapshot() if hasattr(target, "queue_snapshot") else {
        "ready": [task.task_id for task in getattr(target, "task_queue", [])],
        "running": [],
        "waiting": [],
        "failed": [],
        "completed": [],
    }
    return {
        "policy": getattr(target, "policy", SCHEDULER_TYPE),
        "queues": queues,
        "queue_wait_ms_avg": round(sum(queue_wait) / len(queue_wait), 3) if queue_wait else 0,
        "agent_runtime_ms_avg": round(sum(runtime) / len(runtime), 3) if runtime else 0,
        "decisions": {
            t.task_id: {
                "scheduler_decision_reason": t.scheduler_decision_reason,
                "resource_block_reason": t.resource_block_reason,
            }
            for t in all_tasks
            if t.scheduler_decision_reason or t.resource_block_reason
        },
        "selection_log": getattr(target, "selection_log", [])[-50:],
    }


def _record_llm_usage(task: TaskSpec, usage: dict) -> None:
    if not usage:
        return
    task.llm_usage = usage
    llm_usage_totals["input_tokens"] += int(usage.get("input_tokens") or 0)
    llm_usage_totals["output_tokens"] += int(usage.get("output_tokens") or 0)
    llm_usage_totals["total_tokens"] += int(usage.get("total_tokens") or 0)
    llm_usage_totals["latency_ms_total"] += float(usage.get("latency_ms") or 0.0)
    llm_usage_totals["calls"] += 1
    if usage.get("logical_context_reuse_hit") or usage.get("prefix_cache_hit"):
        llm_usage_totals["prefix_cache_hits"] += 1
        llm_usage_totals["logical_context_reuse_hits"] += 1


def _llm_metrics() -> dict:
    calls = int(llm_usage_totals["calls"])
    return {
        "input_tokens": int(llm_usage_totals["input_tokens"]),
        "output_tokens": int(llm_usage_totals["output_tokens"]),
        "total_tokens": int(llm_usage_totals["total_tokens"]),
        "latency_ms": round(float(llm_usage_totals["latency_ms_total"]), 3),
        "latency_ms_avg": round(float(llm_usage_totals["latency_ms_total"]) / calls, 3) if calls else 0.0,
        "prefix_cache_hits": int(llm_usage_totals["prefix_cache_hits"]),
        "prefix_hit_ratio": round(int(llm_usage_totals["prefix_cache_hits"]) / calls, 4) if calls else 0.0,
        "logical_context_reuse_hits": int(llm_usage_totals["logical_context_reuse_hits"]),
        "logical_context_reuse_hit_ratio": round(int(llm_usage_totals["logical_context_reuse_hits"]) / calls, 4) if calls else 0.0,
        "calls": calls,
    }


def _histogram(values: list[float], buckets: list[float] | None = None) -> dict:
    buckets = buckets or [1, 10, 50, 100, 500, 1000, 5000, 10000]
    counts = {str(bucket): 0 for bucket in buckets}
    counts["+Inf"] = 0
    for value in values:
        matched = False
        for bucket in buckets:
            if value <= bucket:
                counts[str(bucket)] += 1
                matched = True
                break
        if not matched:
            counts["+Inf"] += 1
    return {
        "count": len(values),
        "sum": round(sum(values), 3),
        "buckets": counts,
    }


def _trace_json(task: TaskSpec) -> dict:
    context_metrics = context_manager.get_metrics()
    return trace_recorder.to_json(
        task_id=task.task_id,
        queue_wait_ms=task.queue_wait_ms,
        llm_calls=trace_recorder.event_count(task.task_id, "llm.call"),
        token_used=trace_recorder.event_detail_sum(task.task_id, "llm.call", "total_tokens"),
        context_hit_ratio=float(context_metrics.get("cache_hit_ratio") or 0.0),
    )

@app.post("/agents")
async def create_agent(req: CreateAgentRequest):
    if req.agent_name in agents:
        raise HTTPException(status_code=400, detail=f"Agent '{req.agent_name}' 已存在")

    agent = AgentSpec(
        agent_name=req.agent_name,
        role=req.role,
        system_prompt=req.system_prompt,
        model=req.model,
        capability=req.capability,
        max_retries=req.max_retries,
        restart_budget=req.restart_budget,
        fault_domain=req.fault_domain or None,
        memory_max_bytes=req.memory_max_bytes,
        memory_high_bytes=req.memory_high_bytes,
        cpu_max=req.cpu_max or None,
        pids_max=req.pids_max,
    )
    agents[agent.agent_name] = agent
    acb = AgentControlBlock.from_agent_spec(agent)
    agent_controls[agent.agent_name] = acb
    fault_states[agent.agent_name] = WorkerFaultState(agent_name=agent.agent_name, fault_domain=agent.agent_name)
    try:
        _start_worker(agent.agent_name)
    except Exception as e:
        agents.pop(agent.agent_name, None)
        agent_controls.pop(agent.agent_name, None)
        fault_states.pop(agent.agent_name, None)
        agent_auth_tokens.pop(agent.agent_name, None)
        cgroup_bindings.pop(agent.agent_name, None)
        raise HTTPException(status_code=503, detail=str(e))
    _transition_agent(agent.agent_name, AgentStatus.READY, reason="agent.created")
    _persist_agent(agent.agent_name)
    logger.info(f"Agent created: {agent.agent_name} (status: {agent.status})")
    return {"agent_name": agent.agent_name, "status": agent.status}

@app.get("/agents")
async def list_agents():
    return {
        "agents": [            {
                "name": name,
                "role": agent.role,
                "status": agent.status,
                "current_task": agent.current_task_id,
                "worker_pid": (agent_workers.get(name).pid if name in agent_workers else None),
            }
            for name, agent in agents.items()
        ]
    }


@app.get("/agents/{agent_name}/acb")
async def get_agent_acb(agent_name: str):
    if agent_name not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")
    acb = agent_controls.get(agent_name)
    if acb is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 缺少 ACB")
    return acb.to_dict()


@app.post("/agents/{agent_name}/kill")
async def kill_agent(agent_name: str):
    if agent_name not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")
    _stop_worker(agent_name)
    agent = agents[agent_name]
    if agent.status != AgentStatus.KILLED:
        try:
            _transition_agent(agent_name, AgentStatus.KILLED, reason="agent.kill")
        except Exception:
            agent.status = AgentStatus.KILLED
            acb = agent_controls.get(agent_name)
            if acb is not None:
                acb.status = AgentStatus.KILLED
                acb.record_event("agent.force_killed")
    agent_inflight_tasks[agent_name] = 0
    return {"agent_name": agent_name, "status": agent.status}


@app.post("/agents/{agent_name}/restart")
async def restart_agent(agent_name: str):
    if agent_name not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")
    agent = agents[agent_name]
    if agent.status == AgentStatus.KILLED:
        raise HTTPException(status_code=409, detail=f"Agent '{agent_name}' 已 KILLED")
    _stop_worker(agent_name)
    _start_worker(agent_name)
    if agent.status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.WAITING):
        _transition_agent(agent_name, AgentStatus.READY, reason="agent.restart")
    return {"agent_name": agent_name, "status": agent.status}

@app.post("/tasks")
async def submit_task(req: SubmitTaskRequest):
    selected_agent_name = _select_agent_name(req.agent_name, req.required_capability)
    if selected_agent_name is None:
        raise HTTPException(status_code=404, detail="没有匹配任务能力需求的 Agent")
    if selected_agent_name not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{selected_agent_name}' 不存在")

    agent = agents[selected_agent_name]
    if agent.status in (AgentStatus.KILLED, AgentStatus.SUSPENDED, AgentStatus.ISOLATED):
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{selected_agent_name}' 当前状态为 {agent.status}，无法接受新任务"
        )
    if agent.status in (AgentStatus.COMPLETED, AgentStatus.FAILED):
        if agent.status == AgentStatus.FAILED:
            _recover_agent(selected_agent_name, reason="task.submit")
        else:
            agent.status = AgentStatus.READY
            _persist_agent(selected_agent_name)

    # 验证依赖任务是否存在
    for dep_id in req.dependencies:
        if dep_id not in tasks:
            raise HTTPException(status_code=404, detail=f"依赖任务 '{dep_id}' 不存在")

    _record_task_context(req.context_id, selected_agent_name, req.task_input)
    _set_context_handle(selected_agent_name, req.context_id or None)

    task = _make_task(
        agent_name=selected_agent_name,
        task_input=req.task_input,
        context_id=req.context_id,
        priority=req.priority,
        deadline=req.deadline,
        resource_request=req.resource_request,
        token_budget=req.token_budget,
        timeout=req.timeout,
        timeout_ms=req.timeout_ms,
        parent_task_id=req.parent_task_id or None,
        children=req.children,
        trace_id=req.trace_id,
        dependencies=req.dependencies,
        dependency_failure_policies=_edge_failure_policies(req),
        failure_policy=req.failure_policy,
        required_capability=req.required_capability,
        idempotency_key=req.idempotency_key,
        side_effect_level=req.side_effect_level,
        compensation=req.compensation,
        _explicit_fields=_explicit_fields(req),
    )
    tasks[task.task_id] = task
    trace_recorder.ensure_trace(task.trace_id, task.task_id)
    _record_trace_event(task, "task.created", {"agent_name": task.agent_name, "required_capability": task.required_capability})
    scheduler.enqueue(task)
    _record_trace_event(task, "scheduler.enqueue", {"status": task.status})
    agent_inflight_tasks[selected_agent_name] = agent_inflight_tasks.get(selected_agent_name, 0) + 1
    _persist_task(task)
    _wake_scheduler()
    logger.info(f"任务 {task.task_id} 已入队（依赖: {req.dependencies}，等待前面 {scheduler.pending_count - 1} 个任务）")

    return {"task_id": task.task_id, "status": task.status, "message": "任务已加入调度队列"}


@app.post("/tasks/dynamic")
async def submit_dynamic_task(req: SubmitDynamicTaskRequest):
    """
    动态提交任务（由运行中的任务生成）
    """
    selected_agent_name = _select_agent_name(req.agent_name, req.required_capability)
    if selected_agent_name is None:
        raise HTTPException(status_code=404, detail="没有匹配任务能力需求的 Agent")
    if selected_agent_name not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{selected_agent_name}' 不存在")

    agent = agents[selected_agent_name]
    if agent.status in (AgentStatus.KILLED, AgentStatus.SUSPENDED, AgentStatus.ISOLATED):
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{selected_agent_name}' 当前状态为 {agent.status}，无法接受新任务"
        )
    if agent.status in (AgentStatus.COMPLETED, AgentStatus.FAILED):
        if agent.status == AgentStatus.FAILED:
            _recover_agent(selected_agent_name, reason="task.dynamic_submit")
        else:
            agent.status = AgentStatus.READY
            _persist_agent(selected_agent_name)
    
    # 验证父任务是否存在
    if req.parent_task_id and req.parent_task_id not in tasks:
        raise HTTPException(status_code=404, detail=f"父任务 '{req.parent_task_id}' 不存在")

    _record_task_context(req.context_id, selected_agent_name, req.task_input)
    _set_context_handle(selected_agent_name, req.context_id or None)

    task = _make_task(
        agent_name=selected_agent_name,
        task_input=req.task_input,
        context_id=req.context_id,
        priority=req.priority,
        deadline=req.deadline,
        resource_request=req.resource_request,
        token_budget=req.token_budget,
        timeout=req.timeout,
        timeout_ms=req.timeout_ms,
        parent_task_id=req.parent_task_id or None,
        trace_id=req.trace_id,
        dependencies=[req.parent_task_id] if req.parent_task_id else [],
        dependency_failure_policies=_edge_failure_policies(req),
        failure_policy=req.failure_policy,
        required_capability=req.required_capability,
        idempotency_key=req.idempotency_key,
        side_effect_level=req.side_effect_level,
        compensation=req.compensation,
        _explicit_fields=_explicit_fields(req),
    )
    tasks[task.task_id] = task
    trace_recorder.ensure_trace(task.trace_id, task.task_id)
    _record_trace_event(task, "task.created", {"agent_name": task.agent_name, "parent_task_id": req.parent_task_id})
    
    # 如果是 DAG 调度器，使用 add_dynamic_task
    if hasattr(scheduler, 'add_dynamic_task'):
        scheduler.add_dynamic_task(task, req.parent_task_id)
    else:
        scheduler.enqueue(task)
    _record_trace_event(task, "scheduler.enqueue", {"status": task.status})
    agent_inflight_tasks[selected_agent_name] = agent_inflight_tasks.get(selected_agent_name, 0) + 1
    _persist_task(task)
    _wake_scheduler()
    
    logger.info(f"动态任务 {task.task_id} 已入队（父任务: {req.parent_task_id}）")
    return {"task_id": task.task_id, "status": task.status, "message": "动态任务已加入调度队列"}


@app.post("/tasks/{task_id}/spawn")
async def spawn_task(task_id: str, req: SpawnTaskRequest):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail=f"父任务 '{task_id}' 不存在")
    parent = tasks[task_id]
    selected_agent_name = _select_agent_name(req.agent_name, req.required_capability)
    if selected_agent_name is None:
        raise HTTPException(status_code=404, detail="没有匹配任务能力需求的 Agent")
    if selected_agent_name not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{selected_agent_name}' 不存在")
    for dep_id in req.dependencies:
        if dep_id not in tasks:
            raise HTTPException(status_code=404, detail=f"依赖任务 '{dep_id}' 不存在")

    context_id = req.context_id or (parent.context_id if req.inherit_context else "")
    dependency_ids = list(dict.fromkeys(req.dependencies))
    child = _make_task(
        agent_name=selected_agent_name,
        task_input=req.task_input,
        context_id=context_id or None,
        priority=req.priority,
        resource_request=req.resource_request,
        timeout_ms=req.timeout_ms,
        parent_task_id=task_id,
        trace_id=parent.trace_id,
        dependencies=dependency_ids,
        dependency_failure_policies=_edge_failure_policies(req),
        failure_policy=req.failure_policy,
        required_capability=req.required_capability,
        _explicit_fields=_explicit_fields(req),
    )
    tasks[child.task_id] = child
    parent.children.append(child.task_id)
    trace_recorder.ensure_trace(child.trace_id, child.task_id)
    _record_trace_event(child, "task.spawned", {"parent_task_id": task_id, "dependencies": dependency_ids})
    if dependency_ids and all(
        tasks[dep_id].status == TaskStatus.SUCCESS
        or (
            tasks[dep_id].status in (TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED)
            and child.dependency_failure_policies.get(dep_id) == FailureMode.FAIL_OPEN
        )
        for dep_id in dependency_ids
    ):
        child.dependencies = [
            dep_id
            for dep_id in child.dependencies
            if not (
                tasks[dep_id].status in (TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED)
                and child.dependency_failure_policies.get(dep_id) == FailureMode.FAIL_OPEN
            )
        ]
        child.transition_to(TaskStatus.READY, "dependencies_satisfied")
    scheduler.enqueue(child)
    _record_trace_event(child, "scheduler.enqueue", {"status": child.status})
    _persist_task(parent)
    _persist_task(child)
    _wake_scheduler()
    return {"task_id": child.task_id, "status": child.status, "parent_task_id": task_id, "trace_id": child.trace_id}


@app.get("/tasks/{task_id}/children")
async def get_task_children(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task_id, "children": tasks[task_id].children}


@app.get("/tasks/{task_id}/dag")
async def get_task_dag(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    def walk(current_id: str) -> dict:
        current = tasks[current_id]
        return {
            "task_id": current.task_id,
            "agent_name": current.agent_name,
            "status": current.status,
            "dependencies": current.dependencies,
            "children": [walk(child_id) for child_id in current.children if child_id in tasks],
        }

    return walk(task_id)


@app.post("/tasks/{task_id}/dependencies")
async def add_task_dependencies(task_id: str, dependencies: list[str]):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    task = tasks[task_id]
    for dep_id in dependencies:
        if dep_id not in tasks:
            raise HTTPException(status_code=404, detail=f"依赖任务 '{dep_id}' 不存在")
    unique_ids = list(dict.fromkeys(dependencies))
    try:
        if hasattr(scheduler, "add_dependencies"):
            scheduler.add_dependencies(task_id, unique_ids)
        else:
            for dep_id in unique_ids:
                if dep_id not in task.dependencies:
                    task.dependencies.append(dep_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    _persist_task(task)
    return {"task_id": task_id, "dependencies": task.dependencies}

@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    t = tasks[task_id]
    acb = agent_controls.get(t.agent_name)
    runtime = None
    if acb is not None:
        runtime = {
            "agent_name": acb.agent_name,
            "agent_status": acb.status,
            "current_task_id": acb.current_task_id,
            "trace_id": acb.trace_id,
        }
    return {
        "task_id": t.task_id,
        "status": t.status,
        "result": t.result,
        "error": t.error,
        "llm_usage": t.llm_usage,
        "trace_id": t.trace_id,
        "definition": t.definition.model_dump() if t.definition else None,
        "tcb": t.tcb.model_dump() if t.tcb else None,
        "attempts": [attempt.model_dump() for attempt in t.attempts],
        "scheduler": {
            "priority": t.priority,
            "deadline": t.deadline.isoformat() if t.deadline else None,
            "resource_request": t.resource_request,
            "resource_usage": t.resource_usage,
            "resource_lease": t.resource_lease,
            "token_budget": t.token_budget,
            "timeout": t.timeout,
            "failure_policy": t.failure_policy.model_dump(),
            "dependency_failure_policies": {k: v.value for k, v in t.dependency_failure_policies.items()},
            "parent_task_id": t.parent_task_id,
            "queue_wait_ms": t.queue_wait_ms,
            "scheduler_decision_reason": t.scheduler_decision_reason,
            "resource_block_reason": t.resource_block_reason,
            "agent_runtime_ms": t.agent_runtime_ms,
        },
        "runtime": runtime,
        "trace": _trace_json(t),
    }


@app.get("/tasks/{task_id}/trace")
async def get_task_trace(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    trace = _trace_json(tasks[task_id])
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@app.post("/messages")
async def send_message(req: SendMessageRequest):
    if req.from_agent not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{req.from_agent}' 不存在")
    if req.to_agent not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{req.to_agent}' 不存在")

    msg = Message(
        from_agent=req.from_agent,
        to_agent=req.to_agent,
        payload=req.payload,
        topic=req.topic or None,
    )
    await message_router.route(msg)
    return msg.model_dump()


@app.get("/messages/{agent_name}")
async def receive_messages(agent_name: str, limit: int = 50):
    if agent_name not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    messages = await message_router.receive(agent_name, limit=limit)
    return {"messages": [m.model_dump() for m in messages]}


@app.get("/messages/{agent_name}/dead-letter")
async def receive_dead_letters(agent_name: str, limit: int = 50):
    if agent_name not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200
    messages = await message_router.dead_letters(agent_name, limit=limit)
    return {"messages": [m.model_dump() for m in messages]}


@app.get("/scheduler/queues")
async def scheduler_queues():
    target = scheduler
    if hasattr(scheduler, "_inner"):
        target = scheduler._inner
    if hasattr(target, "queue_snapshot"):
        snapshot = target.queue_snapshot()
        return {
            "ready": snapshot.get("ready", []),
            "running": snapshot.get("running", []),
            "waiting": snapshot.get("waiting", []),
            "blocked": snapshot.get("blocked", []),
        }
    return {
        "ready": [task.task_id for task in getattr(target, "task_queue", [])],
        "running": [],
        "waiting": [],
        "blocked": [],
    }

# ───── 调度循环（后台任务） ─────

running_executions: set[asyncio.Task] = set()


def _dequeue_ready_batch() -> list[TaskSpec]:
    if hasattr(scheduler, "dispatch_ready"):
        return scheduler.dispatch_ready()

    batch: list[TaskSpec] = []
    while True:
        task = scheduler.dequeue()
        if task is None:
            break
        if not task.scheduler_decision_reason:
            task.transition_to(TaskStatus.RUNNING, "legacy_dequeue")
        batch.append(task)
    return batch


async def _run_task_once(
    task: TaskSpec,
    agent: AgentSpec,
    task_payload: dict,
    user_message: str,
    lease: ResourceLease | None,
    attempt: TaskAttempt | None = None,
) -> str:
    agent_name = _attempt_agent(task, attempt)
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    attempt_id = attempt.attempt_id if attempt is not None else ""
    pending_task_results[task.task_id] = {"attempt_id": attempt_id, "future": fut}
    span_id = trace_recorder.start_span(task.trace_id, task.task_id, "agent.execute", agent_name)
    try:
        trace_recorder.span_event(task.task_id, span_id, "agent.dispatch", {"agent_name": agent_name})
        _record_trace_event(task, "ipc.wait_connected", {"agent_name": agent_name})
        ok = await message_router.wait_connected(agent_name, timeout_s=5.0)
        if not ok:
            proc = agent_workers.get(agent_name)
            if proc is not None and proc.poll() is not None:
                raise RuntimeError("agent worker crashed")
            raise RuntimeError("agent worker not connected")

        if lease is not None:
            _record_trace_event(task, "resource.monitor", {"lease_id": lease.lease_id})
            within_limits, limit_reason = resource_monitor.monitor_lease(lease)
            if not within_limits:
                raise RuntimeError(f"resource limit exceeded: {limit_reason}")

        _record_trace_event(task, "ipc.send_task", {"agent_name": agent_name})
        message_id = f"exec_{task.task_id}_{uuid4().hex}"
        sent = await message_router.send_event(agent_name, {
            "type": "exec_task",
            "message_id": message_id,
            "task_id": task.task_id,
            "attempt_id": attempt_id,
            "system_prompt": agent.system_prompt or f"你是一个{agent.role}",
            "user_message": user_message,
            "task_input": task_payload,
        })
        if not sent:
            raise RuntimeError("failed to send exec_task")

        timeout_s = (task.timeout_ms / 1000.0) if task.timeout_ms is not None else (task.timeout or (task.failure_policy.timeout_ms / 1000.0))
        try:
            result = await asyncio.wait_for(fut, timeout=timeout_s)
        except asyncio.TimeoutError:
            if attempt is not None:
                attempt.status = "TIMEOUT"
                task.finish_attempt(attempt, failure_reason="task timeout")
                attempt.status = "TIMEOUT"
                _persist_task(task)
            task.transition_to(TaskStatus.TIMEOUT, "task.timeout")
            _record_trace_event(task, "task.timeout", {"timeout_s": timeout_s})
            await message_router.send_event(agent_name, {
                "type": "cancel_task",
                "task_id": task.task_id,
                "attempt_id": attempt_id,
                "reason": "timeout",
            })
            _record_trace_event(task, "task.cancel", {"agent_name": agent_name, "attempt_id": attempt_id})
            await asyncio.sleep(float(os.getenv("AGENTD_CANCEL_GRACE_MS", "500")) / 1000.0)
            cgroup_manager.kill(agent_name)
            _record_trace_event(task, "worker.kill", {"agent_name": agent_name, "attempt_id": attempt_id})
            await resource_monitor.reclaim_async(task.task_id, reason="task timeout")
            state_store.release_leases_for_task(task.task_id, reason="task timeout")
            _record_trace_event(task, "lease.reclaim", {"reason": "task timeout"})
            raise RuntimeError("task timeout")

        status = result.get("status")
        output = result.get("output") or ""
        error = result.get("error") or ""
        usage = result.get("usage") or {}
        if isinstance(usage, dict):
            _record_llm_usage(task, usage)
            _record_trace_event(task, "llm.call", usage)
            if attempt is not None:
                attempt.token_usage = usage
                _persist_task(task)
        if status == "SUCCESS":
            if attempt is not None:
                task.finish_attempt(attempt, result={"output": output}, token_usage=usage if isinstance(usage, dict) else {})
                _persist_task(task)
            trace_recorder.finish_span(task.task_id, span_id, "success")
            return output
        if attempt is not None:
            task.finish_attempt(attempt, result={"output": output}, failure_reason=error or output or "worker error", token_usage=usage if isinstance(usage, dict) else {})
            _persist_task(task)
        raise RuntimeError(error or output or "worker error")
    except asyncio.CancelledError:
        trace_recorder.finish_span(task.task_id, span_id, "cancelled")
        raise
    except Exception:
        if attempt is not None and attempt.completed_at is None:
            task.finish_attempt(attempt, failure_reason="worker error")
            _persist_task(task)
        trace_recorder.finish_span(task.task_id, span_id, "failed")
        raise
    finally:
        pending_task_results.pop(task.task_id, None)


async def _run_task_with_policy(task: TaskSpec) -> tuple[bool, str]:
    agent = agents.get(task.agent_name)
    if agent is None:
        return False, f"agent '{task.agent_name}' not found"

    task_payload = {}
    if task.context_id:
        _record_trace_event(task, "context.build", {"context_id": task.context_id, "agent_name": task.agent_name})
        task_payload["runtime_context"] = context_manager.build_agent_context(task.context_id, task.agent_name)
    task_payload.update(task.task_input)
    user_message = str(task_payload)

    max_attempts = max(int(task.failure_policy.max_retries or 0) + 1, 1)
    last_error = ""
    for attempt in range(max_attempts):
        if task.status == TaskStatus.TIMEOUT:
            task.transition_to(TaskStatus.RETRYING, "task.retry")
            task.transition_to(TaskStatus.RUNNING, "task.retry.dispatch")
        elif task.status == TaskStatus.RETRYING:
            task.transition_to(TaskStatus.RUNNING, "task.retry.dispatch")
        task_attempt = task.create_attempt(
            task.agent_name,
            worker_pid=(agent_workers.get(task.agent_name).pid if task.agent_name in agent_workers else None),
        )
        _persist_task(task)
        try:
            cgroup_ok, cgroup_reason = _cgroup_ready(task.agent_name)
            if not cgroup_ok:
                raise RuntimeError(cgroup_reason)
            _record_trace_event(task, "resource.acquire", {"agent_name": task.agent_name})
            lease = await resource_monitor.acquire_async(task.task_id, task.agent_name, _resource_request_for_task(task, agent))
            if lease is None:
                raise RuntimeError("resource lease not available")
            task.set_resource_lease(lease.to_dict())
            state_store.save_lease(lease)
            _persist_task(task)
            output = await _run_task_once(task, agent, task_payload, user_message, lease, task_attempt)
            return True, output
        except Exception as e:
            last_error = str(e)
            if task_attempt.completed_at is None:
                task.finish_attempt(task_attempt, failure_reason=last_error)
            trace_recorder.increment_retry(task.task_id)
            _record_trace_event(task, "task.retry_or_reclaim", {"error": last_error, "attempt": attempt})
            _isolate_failed_worker(task.agent_name, task.task_id, last_error)
            await resource_monitor.reclaim_async(task.task_id, reason=last_error)
            if attempt < max_attempts - 1:
                await asyncio.sleep(retry_backoff_seconds(attempt))
                continue
            if task.failure_policy.mode == FailureMode.FALLBACK.value and task.failure_policy.fallback_agent:
                continue

    if task.failure_policy.mode == FailureMode.FALLBACK.value and task.failure_policy.fallback_agent:
        if task.status == TaskStatus.TIMEOUT:
            task.transition_to(TaskStatus.FALLBACK, "task.fallback")
        fallback_agent_name = task.failure_policy.fallback_agent
        fallback_attempt = _prepare_fallback_attempt(task, fallback_agent_name)
        if fallback_attempt is not None:
            _record_trace_event(task, "task.fallback", {"fallback_agent": fallback_agent_name})
            agent = agents[fallback_agent_name]
            if task.status == TaskStatus.FALLBACK:
                task.transition_to(TaskStatus.RUNNING, "task.fallback.dispatch")
            try:
                _transition_agent(fallback_agent_name, AgentStatus.RUNNING, task_id=task.task_id, reason="scheduler.fallback_dispatch")
            except InvalidTransitionError:
                pass
            proc = agent_workers.get(fallback_agent_name)
            if proc is None or proc.poll() is not None:
                _stop_worker(fallback_agent_name)
                _start_worker(fallback_agent_name)
            task_payload = {}
            if task.context_id:
                _record_trace_event(task, "context.build", {"context_id": task.context_id, "agent_name": fallback_agent_name})
                task_payload["runtime_context"] = context_manager.build_agent_context(task.context_id, fallback_agent_name)
            task_payload.update(task.task_input)
            user_message = str(task_payload)
            try:
                cgroup_ok, cgroup_reason = _cgroup_ready(fallback_agent_name)
                if not cgroup_ok:
                    raise RuntimeError(cgroup_reason)
                _record_trace_event(task, "resource.acquire", {"agent_name": fallback_agent_name})
                lease = await resource_monitor.acquire_async(task.task_id, fallback_agent_name, _resource_request_for_task(task, agent))
                if lease is None:
                    raise RuntimeError("resource lease not available")
                task.set_resource_lease(lease.to_dict())
                state_store.save_lease(lease)
                _persist_task(task)
                output = await _run_task_once(task, agent, task_payload, user_message, lease, fallback_attempt)
                return True, output
            except Exception as e:
                last_error = str(e)
                if fallback_attempt.completed_at is None:
                    task.finish_attempt(fallback_attempt, failure_reason=last_error)
                _isolate_failed_worker(fallback_agent_name, task.task_id, last_error)
                await resource_monitor.reclaim_async(task.task_id, reason=last_error)

    if task.failure_policy.mode == FailureMode.FALLBACK.value and task.failure_policy.fallback_agent:
        return False, last_error or "worker error"
    if task.failure_policy.mode == FailureMode.DEGRADE.value:
        return True, f"[降级] {last_error or 'worker error'}"
    return False, last_error or "worker error"


async def _execute_task(task: TaskSpec) -> None:
    original_agent = task.agent_name
    try:
        if task.deadline is not None:
            deadline = task.deadline
            now = datetime.now(tz=deadline.tzinfo) if deadline.tzinfo else datetime.now()
            if deadline <= now:
                task.transition_to(TaskStatus.CANCELLED, "deadline.expired")
                task.error = "deadline expired"
                scheduler.fail_task(task.task_id)
                _record_trace_event(task, "task.cancelled", {"reason": "deadline.expired"})
                _persist_task(task)
                return
        agent = agents.get(task.agent_name)
        if agent is None:
            task.transition_to(TaskStatus.CANCELLED, "agent_missing")
            _persist_task(task)
            return
        _prepare_agent_for_task(task, "scheduler.dispatch")
        logger.info(f"调度：任务 {task.task_id} → Agent '{task.agent_name}'")

        ok, output_or_error = await _run_task_with_policy(task)
        agent = agents.get(task.agent_name)
        if ok:
            task.transition_to(TaskStatus.SUCCESS, "task.success")
            task.result = {"role": agent.role if agent else "", "output": output_or_error}
            if agent is not None and agent.status != AgentStatus.KILLED:
                if agent.status == AgentStatus.FAILED:
                    _recover_agent(task.agent_name, task.task_id, reason="task.recovered")
                if agent.status == AgentStatus.RUNNING:
                    _transition_agent(task.agent_name, AgentStatus.COMPLETED, task_id=task.task_id, reason="task.success")
            scheduler.complete_task(task.task_id)
            _record_trace_event(task, "task.success", {"agent_name": task.agent_name})
            _persist_task(task)
            logger.info(f"任务 {task.task_id} ✓")
        else:
            task.transition_to(TaskStatus.FAILED, "task.failed")
            task.error = output_or_error
            if agent is not None and agent.status not in (AgentStatus.FAILED, AgentStatus.KILLED):
                _transition_agent(task.agent_name, AgentStatus.FAILED, task_id=task.task_id, reason="task.failed")
            scheduler.fail_task(task.task_id)
            _record_trace_event(task, "task.failed", {"error": task.error})
            logger.error(f"任务 {task.task_id} ✗: {task.error}")
            task.result = {"role": agent.role if agent else "", "output": f"[错误] {task.error}"}
            _persist_task(task)
    except Exception as e:
        task.transition_to(TaskStatus.FAILED, "task.exception")
        task.error = str(e)
        agent = agents.get(task.agent_name)
        if agent is not None and agent.status not in (AgentStatus.FAILED, AgentStatus.KILLED):
            try:
                _transition_agent(task.agent_name, AgentStatus.FAILED, task_id=task.task_id, reason="task.exception")
            except InvalidTransitionError:
                agent.status = AgentStatus.FAILED
        scheduler.fail_task(task.task_id)
        _record_trace_event(task, "task.exception", {"error": task.error})
        task.result = {"role": agent.role if agent else "", "output": f"[错误] {task.error}"}
        _persist_task(task)
        logger.error(f"任务 {task.task_id} ✗: {task.error}")
    finally:
        await resource_monitor.release_async(task.task_id)
        state_store.release_leases_for_task(task.task_id, reason="task.finished")
        _record_trace_event(task, "resource.release", {"task_id": task.task_id})
        task.resource_usage = resource_monitor.usage.to_dict()
        _persist_task(task)
        agent_inflight_tasks[original_agent] = max(agent_inflight_tasks.get(original_agent, 0) - 1, 0)
        for attempt in task.attempts:
            if attempt.agent_name != original_agent:
                agent_inflight_tasks[attempt.agent_name] = max(agent_inflight_tasks.get(attempt.agent_name, 0) - 1, 0)
                _set_current_task(attempt.agent_name, None)
        _set_current_task(task.agent_name, None)
        _wake_scheduler()


async def _execute_task_with_limits(task: TaskSpec) -> None:
    global_sem = global_dispatch_semaphore
    agent_sem = _agent_semaphore(task.agent_name)
    if global_sem is None:
        async with agent_sem:
            await _execute_task(task)
        return
    async with global_sem:
        async with agent_sem:
            await _execute_task(task)


async def scheduling_loop():
    """后台不断从队列取任务并发执行"""
    while True:
        try:
            event = scheduler_event
            if event is not None:
                await event.wait()
                event.clear()
            batch = _dequeue_ready_batch()
            if not batch:
                if event is None:
                    await asyncio.sleep(0.05)
                continue

            for task in batch:
                execution = asyncio.create_task(_execute_task_with_limits(task))
                running_executions.add(execution)
                execution.add_done_callback(running_executions.discard)
        except Exception as e:
            logger.error(f"调度循环异常: {e}")
            await asyncio.sleep(0.05)

@app.on_event("startup")
async def startup():
    global scheduler_event, global_dispatch_semaphore
    scheduler_event = asyncio.Event()
    scheduler_event.set()
    global_dispatch_semaphore = asyncio.Semaphore(max(resource_monitor.llm_max_concurrent, 1))
    restored_agent_names: list[str] = []
    try:
        for row in state_store.load_agents():
            agent = AgentSpec(**json.loads(row["data"]))
            if agent.status not in (AgentStatus.KILLED, AgentStatus.READY, AgentStatus.CREATED):
                agent.status = AgentStatus.READY
                agent.current_task_id = None
            agents[agent.agent_name] = agent
            agent_controls[agent.agent_name] = AgentControlBlock.from_agent_spec(agent)
            agent_auth_tokens[agent.agent_name] = row.get("auth_token") or secrets.token_urlsafe(24)
            fault_states[agent.agent_name] = WorkerFaultState(agent_name=agent.agent_name, fault_domain=agent.agent_name)
            if agent.status != AgentStatus.KILLED:
                restored_agent_names.append(agent.agent_name)
        for message in state_store.load_mailbox_messages(dead_letter=False):
            message_router.restore_mailbox([message])
        for task in recover_tasks(state_store)[0]:
            if task.task_id not in tasks and task.agent_name in agents:
                tasks[task.task_id] = task
                trace_recorder.ensure_trace(task.trace_id, task.task_id)
                scheduler.enqueue(task)
        json_log("daemon.recovery", recovered_tasks=len(tasks), persistence=state_store.counts())
    except Exception as e:
        logger.error(f"恢复状态失败: {e}")
    global uds_server
    uds_path = os.getenv("AGENTD_UDS_PATH", "/tmp/agent-runtime-agentd.sock")
    try:
        async def _on_task_result(agent_name: str, data: dict) -> None:
            task_id = str(data.get("task_id") or "").strip()
            if not task_id:
                return
            task = tasks.get(task_id)
            if task is None:
                return
            pending = pending_task_results.get(task_id)
            if not pending:
                return
            fut = pending.get("future")
            active_attempt = task.active_attempt
            active_attempt_id = active_attempt.attempt_id if active_attempt is not None else ""
            result_attempt_id = str(data.get("attempt_id") or "")
            if active_attempt is None or result_attempt_id != active_attempt_id:
                _record_trace_event(task, "task.late_result", {"result_attempt_id": result_attempt_id, "active_attempt_id": active_attempt_id or None})
                return
            if fut is None or fut.done():
                _record_trace_event(task, "task.late_result", {"result_attempt_id": result_attempt_id, "reason": "future_done"})
                return
            fut.set_result({
                "agent_name": agent_name,
                "task_id": task_id,
                "attempt_id": result_attempt_id,
                "status": data.get("status"),
                "output": data.get("output"),
                "error": data.get("error"),
                "usage": data.get("usage") or {},
            })

        async def _on_heartbeat(agent_name: str, data: dict) -> None:
            fault = fault_states.setdefault(agent_name, WorkerFaultState(agent_name=agent_name, fault_domain=agent_name))
            fault.heartbeat()
            _persist_agent(agent_name)

        async def _on_agent_message_ack(agent_name: str, data: dict) -> None:
            message_id = str(data.get("message_id") or "")
            if not message_id:
                return
            if state_store.processed_message_exists(message_id, agent_name):
                await message_router.ack(agent_name, message_id)
                return
            state_store.save_processed_message(message_id, agent_name, status="processed", generated_task_id=str(data.get("generated_task_id") or ""))
            for task in tasks.values():
                if task.agent_name == agent_name and task.status == TaskStatus.SUCCESS:
                    _record_trace_event(task, "agent_message_ack", {"message_id": message_id, "agent_name": agent_name})
                    break
            await message_router.ack(agent_name, message_id)

        uds_server = await start_uds_server(
            uds_path,
            message_router,
            task_result_handler=_on_task_result,
            auth_tokens=agent_auth_tokens,
            heartbeat_handler=_on_heartbeat,
            agent_message_ack_handler=_on_agent_message_ack,
        )
        for agent_name in restored_agent_names:
            _start_worker(agent_name)
    except Exception as e:
        logger.error(f"UDS server 启动失败: {e}")
    asyncio.create_task(scheduling_loop())
    logger.info("调度循环已启动")

    async def worker_monitor_loop():
        while True:
            try:
                for name, agent in list(agents.items()):
                    if agent.status == AgentStatus.KILLED:
                        continue
                    proc = agent_workers.get(name)
                    if proc is None:
                        continue
                    fault = fault_states.setdefault(name, WorkerFaultState(agent_name=name, fault_domain=name))
                    if proc.poll() is not None or fault.heartbeat_stale(10.0):
                        current_task_id = agent.current_task_id
                        if current_task_id and current_task_id in tasks:
                            _record_trace_event(
                                tasks[current_task_id],
                                "worker.lost",
                                {"agent_name": name, "reason": "proc_exit" if proc.poll() is not None else "heartbeat_stale"},
                            )
                        _stop_worker(name)
                        if fault.can_restart():
                            fault.record_restart()
                            _start_worker(name)
                        else:
                            _transition_agent(name, AgentStatus.ISOLATED, reason="fault.circuit_open")
            except Exception:
                pass
            await asyncio.sleep(1.0)

    asyncio.create_task(worker_monitor_loop())


@app.on_event("shutdown")
async def shutdown():
    global uds_server
    if uds_server is None:
        pass
    else:
        uds_server.close()
        try:
            await uds_server.wait_closed()
        except Exception:
            pass
        uds_server = None
    for proc in list(agent_workers.values()):
        try:
            proc.terminate()
        except Exception:
            pass
    for name in list(agent_workers.keys()):
        _stop_worker(name)

@app.get("/metrics")
async def metrics():
    status_counts = {}
    for name, agent in agents.items():
        acb = agent_controls.get(name)
        s = (acb.status if acb is not None else agent.status).value
        status_counts[s] = status_counts.get(s, 0) + 1

    result = {
        "agents": {
            "total": len(agents),
            "by_status": status_counts,
        },
        "workers": {
            "total": len(agent_workers),
            "alive": sum(1 for p in agent_workers.values() if p.poll() is None),
            "dead": sum(1 for p in agent_workers.values() if p.poll() is not None),
        },
        "cgroups": {
            name: {
                "binding": binding,
                "stats": cgroup_manager.read_stats(name) if binding.get("ok") is True else {},
            }
            for name, binding in cgroup_bindings.items()
        },
        "tasks": {
            "total": len(tasks),
            "pending": scheduler.pending_count,
            "success": sum(1 for t in tasks.values() if t.status == TaskStatus.SUCCESS),
            "running": sum(1 for t in tasks.values() if t.status == TaskStatus.RUNNING),
            "failed": sum(1 for t in tasks.values() if t.status == TaskStatus.FAILED),
        },
    }
    result["faults"] = {
        name: fault.to_dict()
        for name, fault in fault_states.items()
    }
    result["persistence"] = {
        "db_path": state_store.path,
        "counts": state_store.counts(),
    }
    context_metrics = context_manager.get_metrics()
    llm_metrics = _llm_metrics()
    result["context"] = context_metrics
    result["llm"] = llm_metrics
    result["experiments"] = {
        "token_saving_ratio": context_metrics["token_saving_ratio"],
        "context_build_time_ms": context_metrics["context_build_time_ms"],
        "prefix_hit_ratio": context_metrics["prefix_hit_ratio"],
        "llm_latency_ms": llm_metrics["latency_ms_avg"],
    }
    result["scheduler"] = _scheduler_metrics()

    result["resource"] = resource_monitor.get_snapshot()
    result["histograms"] = {
        "queue_wait_ms": _histogram([t.queue_wait_ms for t in tasks.values() if t.queue_wait_ms is not None]),
        "agent_runtime_ms": _histogram([t.agent_runtime_ms for t in tasks.values() if t.agent_runtime_ms is not None]),
        "llm_latency_ms": _histogram([float(t.llm_usage.get("latency_ms") or 0.0) for t in tasks.values() if t.llm_usage]),
        "context_build_time_ms": _histogram([float(context_metrics.get("context_build_time_ms_avg") or 0.0)] if context_metrics.get("build_hits") else []),
        "resource_lease_count": _histogram([float(len(result["resource"].get("leases", [])))]),
    }

    return result

def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8234, log_level="info")

if __name__ == "__main__":
    main()
