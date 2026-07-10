from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class WorkerFaultState:
    agent_name: str
    max_restarts: int = 3
    restart_budget: int = 3
    restart_count: int = 0
    circuit_open_until: datetime | None = None
    last_heartbeat: datetime | None = None
    fault_domain: str = ""
    fallback_attempts: list[dict] = field(default_factory=list)

    def heartbeat(self) -> None:
        self.last_heartbeat = datetime.now()

    def heartbeat_stale(self, timeout_s: float) -> bool:
        if self.last_heartbeat is None:
            return False
        return (datetime.now() - self.last_heartbeat).total_seconds() > timeout_s

    def can_restart(self) -> bool:
        if self.circuit_open_until and datetime.now() < self.circuit_open_until:
            return False
        return self.restart_count < self.max_restarts and self.restart_budget > 0

    def record_restart(self) -> None:
        self.restart_count += 1
        self.restart_budget -= 1
        if self.restart_count >= self.max_restarts or self.restart_budget <= 0:
            self.circuit_open_until = datetime.now() + timedelta(seconds=30)

    def record_fallback(self, task_id: str, from_agent: str, to_agent: str, attempt_id: str) -> None:
        self.fallback_attempts.append(
            {
                "task_id": task_id,
                "from_agent": from_agent,
                "to_agent": to_agent,
                "attempt_id": attempt_id,
                "created_at": datetime.now().isoformat(),
            }
        )

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "max_restarts": self.max_restarts,
            "restart_budget": self.restart_budget,
            "restart_count": self.restart_count,
            "circuit_open_until": self.circuit_open_until.isoformat() if self.circuit_open_until else None,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "fault_domain": self.fault_domain,
            "fallback_attempts": self.fallback_attempts[-20:],
        }


def retry_backoff_seconds(attempt: int, base: float = 0.2, cap: float = 5.0) -> float:
    return min(cap, base * (2 ** max(attempt, 0)))
