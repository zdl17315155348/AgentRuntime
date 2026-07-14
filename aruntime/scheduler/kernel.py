"""
Agent Runtime Scheduler with ready / waiting / running / failed / completed queues.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Callable, Optional

from aruntime.core.models import AgentSpec, FailureMode, TaskSpec, TaskStatus
from aruntime.scheduler.base import BaseScheduler


@dataclass
class KernelTaskNode:
    task: TaskSpec
    dependencies: set[str] = field(default_factory=set)
    dependents: set[str] = field(default_factory=set)

    @property
    def is_ready(self) -> bool:
        return len(self.dependencies) == 0


ResourceChecker = Callable[[TaskSpec], tuple[bool, str]]
AgentProvider = Callable[[], list[AgentSpec]]


class KernelScheduler(BaseScheduler):
    """Agent runtime scheduler with pluggable task ordering policies."""

    def __init__(
        self,
        policy: str = "priority",
        resource_checker: ResourceChecker | None = None,
        agent_provider: AgentProvider | None = None,
    ):
        super().__init__()
        self.policy = policy
        self.resource_checker = resource_checker
        self.agent_provider = agent_provider
        self.ready_queue: list[TaskSpec] = self.task_queue
        self.waiting_queue: list[TaskSpec] = []
        self.running_table: dict[str, TaskSpec] = {}
        self.failed_queue: list[TaskSpec] = []
        self.completed_queue: list[TaskSpec] = []
        self.blocked_queue = self.waiting_queue
        self.nodes: dict[str, KernelTaskNode] = {}
        self.completed_tasks: set[str] = set()
        self.failed_tasks: set[str] = set()
        self._agent_dispatch_count: dict[str, int] = {}
        self.agent_queues: dict[str, list[str]] = {}
        self.selection_log: list[dict[str, Any]] = []

    def enqueue(self, task: TaskSpec) -> None:
        node = KernelTaskNode(task=task, dependencies=set(task.dependencies))
        self.nodes[task.task_id] = node

        for dep_id in task.dependencies:
            if dep_id in self.nodes:
                self.nodes[dep_id].dependents.add(task.task_id)
            if dep_id in self.completed_tasks:
                node.dependencies.discard(dep_id)

        self.agent_queues.setdefault(task.agent_name, []).append(task.task_id)
        if node.is_ready:
            task.transition_to(TaskStatus.READY, "dependencies_satisfied")
            self._append_ready(task)
        else:
            task.transition_to(TaskStatus.PENDING, "waiting_dependencies")
            self.waiting_queue.append(task)

    def add_dependencies(self, task_id: str, dependency_ids: list[str]) -> None:
        task_node = self.nodes.get(task_id)
        if task_node is None:
            raise KeyError(task_id)
        task = task_node.task
        if task.status in (TaskStatus.RUNNING, TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
            raise ValueError("task state does not allow dependency updates")

        unique_ids = list(dict.fromkeys(dependency_ids))
        if task_id in unique_ids:
            raise ValueError("self dependency is not allowed")
        for dep_id in unique_ids:
            dep_node = self.nodes.get(dep_id)
            if dep_node is None:
                raise KeyError(dep_id)

        for dep_id in unique_ids:
            if dep_id in task_node.dependencies:
                continue
            dep_node = self.nodes[dep_id]
            task_node.dependencies.add(dep_id)
            dep_node.dependents.add(task_id)
            if dep_id in self.completed_tasks:
                task_node.dependencies.discard(dep_id)

        if task in self.ready_queue:
            self.ready_queue.remove(task)
        if task in self.waiting_queue:
            self.waiting_queue.remove(task)
        if task_node.is_ready:
            task.transition_to(TaskStatus.READY, "dependencies_satisfied")
            self._append_ready(task)
        else:
            task.transition_to(TaskStatus.PENDING, "waiting_dependencies")
            self.waiting_queue.append(task)

    def dequeue(self) -> Optional[TaskSpec]:
        dispatched = self.dispatch_ready(limit=1)
        if not dispatched:
            return None
        return dispatched[0]

    def dispatch_ready(self, limit: int | None = None) -> list[TaskSpec]:
        dispatched: list[TaskSpec] = []
        if not self.ready_queue:
            self.wake_waiting()
        self._sort_ready()

        while self.ready_queue and (limit is None or len(dispatched) < limit):
            task = self.ready_queue.pop(0)
            agent = self._select_agent_if_needed(task)
            if agent is None and (task.required_capability or not task.agent_name):
                self.move_to_waiting(task, "no_capability_match")
                task.scheduler_decision_reason = "capability_match:none"
                self.selection_log.append({
                    "task_id": task.task_id,
                    "agent_name": task.agent_name,
                    "selected": False,
                    "reason": "no_capability_match",
                    "at": datetime.now().isoformat(),
                })
                continue
            ok, reason = self.resource_available(task)
            if not ok:
                self.move_to_waiting(task, reason)
                self.selection_log.append({
                    "task_id": task.task_id,
                    "agent_name": task.agent_name,
                    "selected": False,
                    "reason": reason,
                    "at": datetime.now().isoformat(),
                })
                continue
            self._mark_running(task, reason or "resource_available")
            if agent is not None:
                task.agent_name = agent.agent_name
            dispatched.append(task)
            self.selection_log.append({
                "task_id": task.task_id,
                "agent_name": task.agent_name,
                "selected": True,
                "reason": task.scheduler_decision_reason,
                "at": datetime.now().isoformat(),
            })

        return dispatched

    def resource_available(self, task: TaskSpec) -> tuple[bool, str]:
        if self.resource_checker is None:
            return True, "resource_not_checked"
        return self.resource_checker(task)

    def move_to_waiting(self, task: TaskSpec, reason: str) -> None:
        self._remove_from_queues(task)
        task.block(reason)
        self.waiting_queue.append(task)

    def wake_waiting(self) -> None:
        for task in list(self.waiting_queue):
            node = self.nodes.get(task.task_id)
            dependency_ready = node is None or node.is_ready
            if dependency_ready and task.resource_block_reason:
                ok, reason = self.resource_available(task)
                if not ok:
                    task.resource_block_reason = reason
                    continue
                self.waiting_queue.remove(task)
                task.unblock(reason or "resource_available")
                self._append_ready(task)

    def _mark_running(self, task: TaskSpec, reason: str) -> None:
        task.transition_to(TaskStatus.RUNNING, self._decision_reason(task, reason))
        task.resource_block_reason = ""
        self.running_table[task.task_id] = task
        self._agent_dispatch_count[task.agent_name] = self._agent_dispatch_count.get(task.agent_name, 0) + 1

    def complete_task(self, task_id: str) -> None:
        task = self.running_table.pop(task_id, None)
        if task is not None:
            task.transition_to(TaskStatus.SUCCESS, "task.success")
            if task not in self.completed_queue:
                self.completed_queue.append(task)
            self._remove_agent_queue_task(task)
        if task_id not in self.nodes:
            return

        self.completed_tasks.add(task_id)
        node = self.nodes[task_id]
        for dependent_id in node.dependents:
            dep_node = self.nodes.get(dependent_id)
            if dep_node is None:
                continue
            dep_node.dependencies.discard(task_id)
            if dep_node.is_ready and dep_node.task in self.waiting_queue:
                self.waiting_queue.remove(dep_node.task)
                dep_node.task.unblock("dependencies_satisfied")
                self._append_ready(dep_node.task)

    def fail_task(self, task_id: str) -> None:
        task = self.running_table.pop(task_id, None)
        if task is not None:
            task.transition_to(TaskStatus.FAILED, "task.failed")
            if task not in self.failed_queue:
                self.failed_queue.append(task)
            self._remove_agent_queue_task(task)
        self.failed_tasks.add(task_id)
        node = self.nodes.get(task_id)
        if node is None:
            return
        for dependent_id in node.dependents:
            dep_node = self.nodes.get(dependent_id)
            if dep_node is None:
                continue
            edge_mode = dep_node.task.dependency_failure_policies.get(task_id)
            mode = edge_mode
            if mode is None and "failure_policy" in node.task.model_fields_set:
                mode = FailureMode(node.task.failure_policy.mode)
            if mode == FailureMode.FAIL_CLOSED:
                dep_node.task.transition_to(TaskStatus.FAILED, "dependency_fail_closed")
                if dep_node.task not in self.failed_queue:
                    self.failed_queue.append(dep_node.task)
                self.failed_tasks.add(dependent_id)
                self._remove_from_queues(dep_node.task)
            elif mode in (FailureMode.FAIL_OPEN, FailureMode.DEGRADE, FailureMode.FALLBACK):
                dep_node.dependencies.discard(task_id)
                if dep_node.is_ready and dep_node.task in self.waiting_queue:
                    self.waiting_queue.remove(dep_node.task)
                    dep_node.task.unblock(f"dependency_{mode.value}")
                    self._append_ready(dep_node.task)

    def block_task(self, task: TaskSpec) -> None:
        self.running_table.pop(task.task_id, None)
        self._remove_from_queues(task)
        task.block("blocked")
        self.waiting_queue.append(task)

    def wake_blocked(self, task_id: str) -> bool:
        for task in list(self.waiting_queue):
            if task.task_id == task_id:
                self.waiting_queue.remove(task)
                task.unblock("blocked_wake")
                self._append_ready(task)
                return True
        return False

    def queue_snapshot(self) -> dict[str, list[str]]:
        return {
            "ready": [task.task_id for task in self.ready_queue],
            "running": list(self.running_table.keys()),
            "waiting": [task.task_id for task in self.waiting_queue],
            "failed": [task.task_id for task in self.failed_queue],
            "completed": [task.task_id for task in self.completed_queue],
            "blocked": [task.task_id for task in self.waiting_queue if task.resource_block_reason],
            "agent_queues": self.agent_queues,
        }

    def _append_ready(self, task: TaskSpec) -> None:
        self.ready_queue.append(task)
        self._sort_ready()

    def _remove_from_queues(self, task: TaskSpec) -> None:
        for queue in (self.ready_queue, self.waiting_queue, self.failed_queue, self.completed_queue):
            if task in queue:
                queue.remove(task)

    def _sort_ready(self) -> None:
        self.ready_queue.sort(key=self._sort_key)

    def _sort_key(self, task: TaskSpec) -> tuple[Any, ...]:
        if self.policy == "fifo":
            return (task.created_at,)
        if self.policy == "priority":
            return (-self._aged_priority(task), task.created_at)
        if self.policy == "deadline":
            return (self._deadline_value(task), -self._aged_priority(task), task.created_at)
        if self.policy == "fair_share":
            return (self._agent_dispatch_count.get(task.agent_name, 0), -self._aged_priority(task), task.created_at)
        if self.policy == "resource_aware":
            return (self._resource_weight(task), -self._aged_priority(task), task.created_at)
        if self.policy == "capability_aware":
            return (-self._capability_score(task), -self._aged_priority(task), task.created_at)
        if self.policy == "cost_aware":
            return (self._cost_score(task), -self._aged_priority(task), task.created_at)
        if self.policy == "reliability_aware":
            return (-self._reliability_score(task), -self._aged_priority(task), task.created_at)
        return (-self._aged_priority(task), task.created_at)

    def _aged_priority(self, task: TaskSpec) -> float:
        waited_s = max((datetime.now() - task.created_at).total_seconds(), 0.0)
        return float(task.priority) + waited_s / 30.0

    def _decision_reason(self, task: TaskSpec, resource_reason: str) -> str:
        if self.policy == "fifo":
            return "fifo_order"
        if self.policy == "priority":
            return f"priority={task.priority}"
        if self.policy == "deadline":
            return "earliest_deadline"
        if self.policy == "fair_share":
            return f"fair_share_agent_count={self._agent_dispatch_count.get(task.agent_name, 0)}"
        if self.policy == "resource_aware":
            details = self._resource_score_details(task)
            return f"{resource_reason}; resource_score={json.dumps(details, sort_keys=True)}"
        if self.policy == "capability_aware":
            return resource_reason if resource_reason.startswith("capability_match") else (task.scheduler_decision_reason or "capability_match")
        if self.policy == "cost_aware":
            return resource_reason if resource_reason.startswith("capability_match") else (task.scheduler_decision_reason or "cost_aware")
        if self.policy == "reliability_aware":
            return resource_reason if resource_reason.startswith("capability_match") else (task.scheduler_decision_reason or "reliability_aware")
        return self.policy

    def _deadline_value(self, task: TaskSpec) -> float:
        if task.deadline is None:
            return float("inf")
        deadline = task.deadline
        if deadline.tzinfo is not None:
            return deadline.timestamp()
        return deadline.replace(tzinfo=timezone.utc).timestamp()

    def _resource_weight(self, task: TaskSpec) -> float:
        return self._resource_score_details(task)["final_score"]

    def _resource_score_details(self, task: TaskSpec) -> dict[str, float]:
        memory = self._requested_number(task, "memory_max_bytes")
        tokens = self._requested_number(task, "token_budget")
        if task.token_budget and tokens <= 0:
            tokens = float(task.token_budget)
        llm = self._requested_number(task, "llm_max_concurrent")

        candidates = list(self.ready_queue)
        if task not in candidates:
            candidates.append(task)
        memory_base = self._max_requested(candidates, "memory_max_bytes", include_task_budget=False)
        token_base = self._max_requested(candidates, "token_budget", include_task_budget=True)
        llm_base = self._max_requested(candidates, "llm_max_concurrent", include_task_budget=False)

        memory_ratio = self._ratio(memory, memory_base)
        token_ratio = self._ratio(tokens, token_base)
        llm_ratio = self._ratio(llm, llm_base)
        final_score = (memory_ratio + token_ratio + llm_ratio) / 3.0
        return {
            "memory_ratio": round(memory_ratio, 4),
            "token_ratio": round(token_ratio, 4),
            "llm_ratio": round(llm_ratio, 4),
            "final_score": round(final_score, 4),
        }

    def _requested_number(self, task: TaskSpec, key: str) -> float:
        request = task.resource_request or {}
        value = request.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        return 0.0

    def _max_requested(self, tasks: list[TaskSpec], key: str, include_task_budget: bool) -> float:
        values: list[float] = []
        for item in tasks:
            value = self._requested_number(item, key)
            if include_task_budget and item.token_budget and value <= 0:
                value = float(item.token_budget)
            values.append(value)
        return max(values or [0.0])

    def _ratio(self, value: float, denominator: float) -> float:
        if denominator <= 0:
            return 0.0
        return min(value / denominator, 1.0)

    def _select_agent_if_needed(self, task: TaskSpec) -> AgentSpec | None:
        if not task.required_capability and task.agent_name:
            return None
        agents = self.agent_provider() if self.agent_provider else []
        return self.match_agent(task, agents)

    def _match_capability(self, task: TaskSpec, agent: AgentSpec) -> bool:
        req = task.required_capability or {}
        cap = agent.capability
        if req.get("can_plan") and not cap.can_plan:
            return False
        if req.get("can_code") and not cap.can_code:
            return False
        if req.get("can_test") and not cap.can_test:
            return False
        if req.get("can_review") and not cap.can_review:
            return False
        language = req.get("language")
        if language and language not in cap.languages:
            return False
        tool = req.get("tool")
        if tool and tool not in cap.tools:
            return False
        return True

    def match_agent(self, task: TaskSpec, agents: list[AgentSpec]) -> AgentSpec | None:
        matched = [agent for agent in agents if self._match_capability(task, agent)]
        if not matched:
            task.scheduler_decision_reason = "capability_match:none"
            return None
        matched.sort(key=self._match_agent_key)
        selected = matched[0]
        task.scheduler_decision_reason = self._decision_reason(
            task,
            f"capability_match: selected={selected.agent_name}, reliability={selected.capability.reliability_score}",
        )
        task.agent_name = selected.agent_name
        return selected

    def _match_agent_key(self, agent: AgentSpec) -> tuple[Any, ...]:
        return (
            -float(agent.capability.reliability_score),
            int(agent.capability.cost_level),
            agent.agent_name,
        )

    def _capability_score(self, task: TaskSpec) -> float:
        req = task.required_capability or {}
        score = 0.0
        for key in ("can_plan", "can_code", "can_test", "can_review"):
            if req.get(key):
                score += 1.0
        if req.get("language"):
            score += 1.0
        return score

    def _cost_score(self, task: TaskSpec) -> float:
        agent = self._find_agent(task.agent_name)
        return float(agent.capability.cost_level if agent else 0)

    def _reliability_score(self, task: TaskSpec) -> float:
        agent = self._find_agent(task.agent_name)
        return float(agent.capability.reliability_score if agent else 0.0)

    def _find_agent(self, agent_name: str | None) -> AgentSpec | None:
        if not agent_name or self.agent_provider is None:
            return None
        for agent in self.agent_provider():
            if agent.agent_name == agent_name:
                return agent
        return None

    def _elapsed_ms(self, start: datetime, end: datetime) -> float:
        return round((end - start).total_seconds() * 1000, 3)

    def _remove_agent_queue_task(self, task: TaskSpec) -> None:
        queue = self.agent_queues.get(task.agent_name)
        if queue and task.task_id in queue:
            queue.remove(task.task_id)

    @property
    def pending_count(self) -> int:
        return len(self.ready_queue) + len(self.waiting_queue)

    @property
    def ready_count(self) -> int:
        return len(self.ready_queue)

    @property
    def running_count(self) -> int:
        return len(self.running_table)

    @property
    def waiting_count(self) -> int:
        return len(self.waiting_queue)

    @property
    def blocked_count(self) -> int:
        return sum(1 for task in self.waiting_queue if task.resource_block_reason)

    @property
    def running_queue(self) -> dict[str, TaskSpec]:
        return self.running_table
