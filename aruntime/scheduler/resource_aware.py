"""
资源感知调度器
包装任意 BaseScheduler，在 dequeue 时增加资源检查
"""

from typing import Optional, Dict
from aruntime.core.models import TaskSpec, AgentSpec, TaskStatus
from aruntime.resource.monitor import ResourceMonitor
from aruntime.scheduler.base import BaseScheduler


class ResourceAwareScheduler(BaseScheduler):
    """资源感知调度器（装饰器模式，包装 inner 调度器）"""

    def __init__(self, inner: BaseScheduler, monitor: ResourceMonitor,
                 agents_dict: Dict[str, AgentSpec]):
        super().__init__()
        self._inner = inner
        self._monitor = monitor
        self._agents = agents_dict

    # ---- 委托给 inner ----

    def enqueue(self, task: TaskSpec) -> None:
        self._inner.enqueue(task)

    def complete_task(self, task_id: str) -> None:
        self._inner.complete_task(task_id)

    def fail_task(self, task_id: str) -> None:
        self._inner.fail_task(task_id)

    # ---- 核心：带资源检查的 dequeue ----

    def dequeue(self) -> Optional[TaskSpec]:
        """遍历队列，返回第一个资源条件满足的就绪任务"""
        queue = self._inner.task_queue
        for i, task in enumerate(queue):
            agent = self._agents.get(task.agent_name)
            if agent is None:
                continue

            # DAG 就绪检查：委托 inner 判断
            if hasattr(self._inner, 'nodes'):
                node = self._inner.nodes.get(task.task_id)
                if node is None or not node.is_ready:
                    continue

            # 资源检查
            if self._monitor.has_enough(
                memory_max_bytes=agent.memory_max_bytes,
                cpu_max=agent.cpu_max,
                llm_max_concurrent=agent.llm_max_concurrent,
            ):
                task = queue.pop(i)
                task.status = TaskStatus.RUNNING
                return task

        return None

    @property
    def pending_count(self) -> int:
        return self._inner.pending_count
