"""
Kernel-style scheduler with ready / running / waiting / blocked queues.
"""

from dataclasses import dataclass, field
from typing import Optional

from aruntime.core.models import FailurePolicy, TaskSpec, TaskStatus
from aruntime.scheduler.base import BaseScheduler


@dataclass
class KernelTaskNode:
    task: TaskSpec
    dependencies: set[str] = field(default_factory=set)
    dependents: set[str] = field(default_factory=set)

    @property
    def is_ready(self) -> bool:
        return len(self.dependencies) == 0


class KernelScheduler(BaseScheduler):
    """Small OS-style scheduler queue model."""

    def __init__(self):
        super().__init__()
        self.ready_queue = self.task_queue
        self.running_queue: dict[str, TaskSpec] = {}
        self.waiting_queue: list[TaskSpec] = []
        self.blocked_queue: list[TaskSpec] = []
        self.nodes: dict[str, KernelTaskNode] = {}
        self.completed_tasks: set[str] = set()
        self.failed_tasks: set[str] = set()

    def enqueue(self, task: TaskSpec) -> None:
        node = KernelTaskNode(task=task, dependencies=set(task.dependencies))
        self.nodes[task.task_id] = node

        for dep_id in task.dependencies:
            if dep_id in self.nodes:
                self.nodes[dep_id].dependents.add(task.task_id)
            if dep_id in self.completed_tasks:
                node.dependencies.discard(dep_id)

        if node.is_ready:
            task.status = TaskStatus.READY
            self._append_ready(task)
        else:
            task.status = TaskStatus.PENDING
            self.waiting_queue.append(task)

    def dequeue(self) -> Optional[TaskSpec]:
        if not self.ready_queue:
            return None
        task = self.ready_queue.pop(0)
        task.status = TaskStatus.RUNNING
        self.running_queue[task.task_id] = task
        return task

    def complete_task(self, task_id: str) -> None:
        self.running_queue.pop(task_id, None)
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
                dep_node.task.status = TaskStatus.READY
                self._append_ready(dep_node.task)

    def fail_task(self, task_id: str) -> None:
        self.running_queue.pop(task_id, None)
        self.failed_tasks.add(task_id)
        node = self.nodes.get(task_id)
        if node is None:
            return
        if node.task.failure_policy != FailurePolicy.FAIL_CLOSED:
            return
        for dependent_id in node.dependents:
            dep_node = self.nodes.get(dependent_id)
            if dep_node is None:
                continue
            dep_node.task.status = TaskStatus.FAILED
            self.failed_tasks.add(dependent_id)
            self._remove_from_queues(dep_node.task)

    def block_task(self, task: TaskSpec) -> None:
        self.running_queue.pop(task.task_id, None)
        self._remove_from_queues(task)
        task.status = TaskStatus.PENDING
        self.blocked_queue.append(task)

    def wake_blocked(self, task_id: str) -> bool:
        for task in list(self.blocked_queue):
            if task.task_id == task_id:
                self.blocked_queue.remove(task)
                task.status = TaskStatus.READY
                self._append_ready(task)
                return True
        return False

    def queue_snapshot(self) -> dict[str, list[str]]:
        return {
            "ready": [task.task_id for task in self.ready_queue],
            "running": list(self.running_queue.keys()),
            "waiting": [task.task_id for task in self.waiting_queue],
            "blocked": [task.task_id for task in self.blocked_queue],
        }

    def _append_ready(self, task: TaskSpec) -> None:
        self.ready_queue.append(task)
        self.ready_queue.sort(key=lambda t: (-t.priority, t.created_at))

    def _remove_from_queues(self, task: TaskSpec) -> None:
        for queue in (self.ready_queue, self.waiting_queue, self.blocked_queue):
            if task in queue:
                queue.remove(task)

    @property
    def pending_count(self) -> int:
        return len(self.ready_queue) + len(self.waiting_queue) + len(self.blocked_queue)

    @property
    def ready_count(self) -> int:
        return len(self.ready_queue)

    @property
    def running_count(self) -> int:
        return len(self.running_queue)

    @property
    def waiting_count(self) -> int:
        return len(self.waiting_queue)

    @property
    def blocked_count(self) -> int:
        return len(self.blocked_queue)
