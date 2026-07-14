from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from aruntime.core.models import AgentSpec, AgentStatus


@dataclass
class ResourceQuota:
    memory_max_bytes: int | None = None
    memory_high_bytes: int | None = None
    cpu_max: str | None = None
    pids_max: int | None = None
    llm_max_concurrent: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_max_bytes": self.memory_max_bytes,
            "memory_high_bytes": self.memory_high_bytes,
            "cpu_max": self.cpu_max,
            "pids_max": self.pids_max,
            "llm_max_concurrent": self.llm_max_concurrent,
        }


@dataclass
class ContextHandle:
    context_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"context_id": self.context_id}


@dataclass
class TimelineEvent:
    timestamp: datetime
    event: str
    from_status: AgentStatus | None = None
    to_status: AgentStatus | None = None
    task_id: str | None = None
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "event": self.event,
            "from_status": self.from_status.value if self.from_status else None,
            "to_status": self.to_status.value if self.to_status else None,
            "task_id": self.task_id,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass
class AgentControlBlock:
    agent_name: str
    status: AgentStatus = AgentStatus.CREATED
    current_task_id: str | None = None
    resource_quota: ResourceQuota = field(default_factory=ResourceQuota)
    context_handle: ContextHandle = field(default_factory=ContextHandle)
    fault_domain: str = ""
    trace_id: str = field(default_factory=lambda: f"trace_{uuid4().hex}")
    mailbox: str | None = None
    ipc_endpoint: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    timeline: list[TimelineEvent] = field(default_factory=list)
    _ALLOWED_TRANSITIONS = {
        AgentStatus.CREATED: {AgentStatus.READY, AgentStatus.FAILED},
        AgentStatus.READY: {AgentStatus.RUNNING, AgentStatus.SUSPENDED, AgentStatus.LOST, AgentStatus.KILLED},
        AgentStatus.RUNNING: {AgentStatus.WAITING, AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.ISOLATED, AgentStatus.LOST, AgentStatus.KILLED},
        AgentStatus.WAITING: {AgentStatus.READY, AgentStatus.FAILED, AgentStatus.LOST, AgentStatus.KILLED},
        AgentStatus.FAILED: {AgentStatus.RECOVERING, AgentStatus.ISOLATED, AgentStatus.KILLED},
        AgentStatus.LOST: {AgentStatus.RECOVERING, AgentStatus.ISOLATED, AgentStatus.KILLED},
        AgentStatus.RECOVERING: {AgentStatus.READY, AgentStatus.KILLED},
        AgentStatus.ISOLATED: {AgentStatus.READY, AgentStatus.KILLED},
        AgentStatus.SUSPENDED: {AgentStatus.READY, AgentStatus.KILLED},
        AgentStatus.COMPLETED: set(),
        AgentStatus.KILLED: set(),
    }

    @classmethod
    def from_agent_spec(cls, agent: AgentSpec) -> "AgentControlBlock":
        return cls(
            agent_name=agent.agent_name,
            status=agent.status,
            resource_quota=ResourceQuota(
                memory_max_bytes=agent.memory_max_bytes,
                memory_high_bytes=agent.memory_high_bytes,
                cpu_max=agent.cpu_max,
                pids_max=agent.pids_max,
                llm_max_concurrent=agent.llm_max_concurrent,
            ),
            fault_domain=agent.agent_name,
        )

    def record_event(
        self,
        event: str,
        task_id: str | None = None,
        reason: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.timeline.append(
            TimelineEvent(
                timestamp=datetime.now(),
                event=event,
                task_id=task_id,
                reason=reason,
                detail=detail or {},
            )
        )
        self.updated_at = datetime.now()

    def record_transition(
        self,
        from_status: AgentStatus,
        to_status: AgentStatus,
        task_id: str | None = None,
        reason: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.timeline.append(
            TimelineEvent(
                timestamp=datetime.now(),
                event="agent.transition",
                from_status=from_status,
                to_status=to_status,
                task_id=task_id,
                reason=reason,
                detail=detail or {},
            )
        )
        self.updated_at = datetime.now()

    def transition_to(
        self,
        target: AgentStatus,
        task_id: str | None = None,
        reason: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        if target not in self._ALLOWED_TRANSITIONS.get(self.status, set()):
            raise ValueError(f"invalid agent transition: {self.status} -> {target}")
        old = self.status
        self.status = target
        self.record_transition(old, target, task_id=task_id, reason=reason, detail=detail)

    def set_current_task(self, task_id: str | None) -> None:
        self.current_task_id = task_id
        self.updated_at = datetime.now()

    def set_context(self, context_id: str | None) -> None:
        self.context_handle.context_id = context_id
        self.updated_at = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "status": self.status.value,
            "current_task_id": self.current_task_id,
            "resource_quota": self.resource_quota.to_dict(),
            "context_handle": self.context_handle.to_dict(),
            "fault_domain": self.fault_domain,
            "trace_id": self.trace_id,
            "mailbox": self.mailbox,
            "ipc_endpoint": self.ipc_endpoint,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "timeline": [event.to_dict() for event in self.timeline],
        }
