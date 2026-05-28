"""
调度器基类
定义调度器的统一接口
"""

from abc import ABC, abstractmethod
from typing import Optional, List
from aruntime.core.models import TaskSpec, TaskStatus


class BaseScheduler(ABC):
    """调度器抽象基类"""

    def __init__(self):
        self.task_queue: List[TaskSpec] = []   # 任务队列

    @abstractmethod
    def enqueue(self, task: TaskSpec) -> None:
        """将任务加入调度队列"""
        pass

    @abstractmethod
    def dequeue(self) -> Optional[TaskSpec]:
        """从队列中取出一个可执行的任务"""
        pass

    def complete_task(self, task_id: str) -> None:
        """标记任务完成，释放依赖"""
        pass

    def fail_task(self, task_id: str) -> None:
        """标记任务失败"""
        pass