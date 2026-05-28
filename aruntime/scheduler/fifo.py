"""
FIFO 调度器
按任务提交顺序执行
"""

from typing import Optional
from aruntime.core.models import TaskSpec, TaskStatus
from aruntime.scheduler.base import BaseScheduler


class FIFOScheduler(BaseScheduler):
    """先进先出调度器"""

    def enqueue(self, task: TaskSpec) -> None:
        """将任务加入队列尾部，标记为 READY"""
        task.status = TaskStatus.READY
        self.task_queue.append(task)

    def dequeue(self) -> Optional[TaskSpec]:
        """从队列头部取出一个任务"""
        if not self.task_queue:
            return None
        
        task = self.task_queue.pop(0)
        task.status = TaskStatus.RUNNING
        return task

    def complete_task(self, task_id: str) -> None:
        """标记任务完成"""
        # FIFO 调度器不跟踪依赖，留空
        pass

    def fail_task(self, task_id: str) -> None:
        """标记任务失败"""
        pass

    @property
    def pending_count(self) -> int:
        """队列中等待的任务数"""
        return len(self.task_queue)