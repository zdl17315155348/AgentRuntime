from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import uuid4


class ResourceClass(Enum):
    CPU = "cpu"
    MEMORY = "memory"
    LLM_CONCURRENCY = "llm_concurrency"
    TOKEN = "token"
    TOOL = "tool"
    KV_CACHE = "kv_cache"
    NETWORK = "network"


@dataclass
class ResourceQuota:
    limits: dict[ResourceClass, float] = field(default_factory=dict)

    def get(self, resource_class: ResourceClass, default: float = 0.0) -> float:
        return float(self.limits.get(resource_class, default) or 0.0)


@dataclass
class ResourceRequest:
    amounts: dict[ResourceClass, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ResourceRequest":
        amounts: dict[ResourceClass, float] = {}
        aliases = {
            "memory_max_bytes": ResourceClass.MEMORY,
            "cpu_max": ResourceClass.CPU,
            "llm_max_concurrent": ResourceClass.LLM_CONCURRENCY,
            "token_budget": ResourceClass.TOKEN,
        }
        for key, value in (data or {}).items():
            if isinstance(value, (int, float)):
                key_text = str(key)
                if key_text in aliases:
                    resource_class = aliases[key_text]
                else:
                    try:
                        resource_class = ResourceClass(key_text)
                    except ValueError:
                        continue
                amounts[resource_class] = float(value)
        return cls(amounts=amounts)

    def get(self, resource_class: ResourceClass, default: float = 0.0) -> float:
        return float(self.amounts.get(resource_class, default) or 0.0)


@dataclass
class ResourceUsage:
    used: dict[ResourceClass, float] = field(default_factory=dict)

    def add(self, resource_class: ResourceClass, amount: float) -> None:
        self.used[resource_class] = self.get(resource_class) + float(amount)

    def sub(self, resource_class: ResourceClass, amount: float) -> None:
        self.used[resource_class] = max(0.0, self.get(resource_class) - float(amount))

    def get(self, resource_class: ResourceClass, default: float = 0.0) -> float:
        return float(self.used.get(resource_class, default) or 0.0)

    def to_dict(self) -> dict[str, float]:
        return {resource_class.value: amount for resource_class, amount in self.used.items()}


@dataclass
class ResourceLease:
    task_id: str
    agent_name: str
    request: ResourceRequest
    lease_id: str = field(default_factory=lambda: f"lease_{uuid4().hex}")
    created_at: datetime = field(default_factory=datetime.now)
    released_at: datetime | None = None
    status: str = "active"
    reason: str = ""

    def release(self) -> None:
        self.status = "released"
        self.released_at = datetime.now()

    def to_dict(self) -> dict:
        return {
            "lease_id": self.lease_id,
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "request": {k.value: v for k, v in self.request.amounts.items()},
            "created_at": self.created_at.isoformat(),
            "released_at": self.released_at.isoformat() if self.released_at else None,
            "status": self.status,
            "reason": self.reason,
        }


class ResourceReclaimer:
    def __init__(self):
        self.reclaimed: list[ResourceLease] = []

    def reclaim(self, lease: ResourceLease, reason: str = "") -> None:
        lease.reason = reason
        lease.release()
        self.reclaimed.append(lease)
