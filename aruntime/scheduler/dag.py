"""
DAG 调度器
支持任务依赖、拓扑排序、动态任务生成
"""

from typing import Optional, List, Dict, Set
from collections import defaultdict, deque

from aruntime.core.models import FailureMode, TaskSpec, TaskStatus
from aruntime.scheduler.base import BaseScheduler


class DAGNode:
    """DAG 节点，封装任务及其依赖关系"""
    def __init__(self, task: TaskSpec):
        self.task = task
        self.dependencies: Set[str] = set(task.dependencies)
        self.dependents: Set[str] = set()  # 依赖此任务的任务 ID 列表
    
    @property
    def task_id(self) -> str:
        return self.task.task_id
    
    @property
    def is_ready(self) -> bool:
        """检查任务是否就绪（所有依赖都已完成）"""
        return len(self.dependencies) == 0


class DAGScheduler(BaseScheduler):
    """基于 DAG 的调度器，支持任务依赖"""

    def __init__(self):
        super().__init__()
        self.nodes: Dict[str, DAGNode] = {}  # task_id -> DAGNode
        self.completed_tasks: Set[str] = set()  # 已完成的任务 ID
        self.failed_tasks: Set[str] = set()  # 失败的任务 ID
        self.waiting_queue: list[TaskSpec] = []
    
    def enqueue(self, task: TaskSpec) -> None:
        """
        将任务加入 DAG
        
        自动建立依赖关系：
        - 任务 A 的 dependencies 包含任务 B → B 是 A 的前驱，A 依赖 B
        """
        node = DAGNode(task)
        self.nodes[task.task_id] = node
        
        # 建立反向依赖关系
        for dep_id in task.dependencies:
            if dep_id in self.nodes:
                self.nodes[dep_id].dependents.add(task.task_id)
            # 如果依赖已完成，从 dependencies 中移除
            if dep_id in self.completed_tasks and dep_id in node.dependencies:
                node.dependencies.remove(dep_id)
        
        # 如果没有依赖，直接标记为 READY
        if len(node.dependencies) == 0:
            task.transition_to(TaskStatus.READY, "dependencies_satisfied")
        else:
            task.transition_to(TaskStatus.PENDING, "waiting_dependencies")
            self.waiting_queue.append(task)
        
        self.task_queue.append(task)
    
    def dequeue(self) -> Optional[TaskSpec]:
        """
        从 DAG 中取出一个就绪的任务
        
        就绪条件：
        1. 所有依赖任务都已完成
        2. 任务状态为 READY
        """
        # 遍历所有任务，找到第一个就绪的
        for task in self.task_queue:
            node = self.nodes.get(task.task_id)
            if node and node.is_ready:
                self.task_queue.remove(task)
                if task in self.waiting_queue:
                    self.waiting_queue.remove(task)
                task.transition_to(TaskStatus.RUNNING, "dag_ready")
                return task
        
        return None
    
    def complete_task(self, task_id: str) -> None:
        """
        标记任务完成，释放依赖
        
        当任务完成后：
        1. 从所有依赖它的任务的 dependencies 中移除
        2. 如果某个任务的 dependencies 为空，则标记为 READY
        """
        if task_id not in self.nodes:
            return
        
        self.completed_tasks.add(task_id)
        node = self.nodes[task_id]
        
        # 更新所有依赖此任务的节点
        for dependent_id in node.dependents:
            if dependent_id in self.nodes:
                dep_node = self.nodes[dependent_id]
                if task_id in dep_node.dependencies:
                    dep_node.dependencies.remove(task_id)
                    if len(dep_node.dependencies) == 0:
                        dep_node.task.transition_to(TaskStatus.READY, "dependencies_satisfied")
                        if dep_node.task in self.waiting_queue:
                            self.waiting_queue.remove(dep_node.task)
    
    def fail_task(self, task_id: str) -> None:
        """
        标记任务失败
        
        默认失败策略为 isolate：
        - 只记录当前失败任务
        - 不默认级联失败下游任务
        - 下游任务保持等待，等待后续容错策略处理
        显式 fail-closed 时才阻断下游。
        """
        if task_id not in self.nodes:
            return
        
        self.failed_tasks.add(task_id)
        node = self.nodes[task_id]
        for dependent_id in node.dependents:
            if dependent_id in self.nodes and dependent_id not in self.failed_tasks:
                dep_node = self.nodes[dependent_id]
                edge_mode = dep_node.task.dependency_failure_policies.get(task_id)
                mode = edge_mode
                if mode is None and "failure_policy" in node.task.model_fields_set:
                    mode = FailureMode(node.task.failure_policy.mode)
                if mode == FailureMode.FAIL_CLOSED:
                    dep_node.task.transition_to(TaskStatus.FAILED, "dependency_fail_closed")
                    self.fail_task(dependent_id)
                elif mode in (FailureMode.FAIL_OPEN, FailureMode.DEGRADE, FailureMode.FALLBACK):
                    dep_node.dependencies.discard(task_id)
                    if dep_node.is_ready:
                        dep_node.task.transition_to(TaskStatus.READY, f"dependency_{mode.value}")
    
    def topological_sort(self) -> List[str]:
        """
        拓扑排序
        
        返回按依赖关系排序的任务 ID 列表
        用于调试和可视化
        """
        in_degree = {task_id: len(node.dependencies) for task_id, node in self.nodes.items()}
        queue = deque([task_id for task_id, degree in in_degree.items() if degree == 0])
        result = []
        
        while queue:
            task_id = queue.popleft()
            result.append(task_id)
            
            node = self.nodes.get(task_id)
            if node:
                for dependent_id in node.dependents:
                    in_degree[dependent_id] -= 1
                    if in_degree[dependent_id] == 0:
                        queue.append(dependent_id)
        
        # 检测是否有环
        if len(result) != len(self.nodes):
            raise ValueError("DAG 中存在循环依赖")
        
        return result
    
    def add_dynamic_task(self, task: TaskSpec, parent_task_id: Optional[str] = None) -> None:
        """
        动态添加任务（由运行中的任务生成）
        
        参数:
            task: 新任务
            parent_task_id: 父任务 ID（新任务依赖父任务完成）
        """
        if parent_task_id and parent_task_id in self.nodes:
            task.dependencies.append(parent_task_id)
        
        self.enqueue(task)

    def add_dependencies(self, task_id: str, dependency_ids: list[str]) -> None:
        node = self.nodes.get(task_id)
        if node is None:
            raise KeyError(task_id)
        task = node.task
        if task.status in (TaskStatus.RUNNING, TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
            raise ValueError("task state does not allow dependency updates")
        unique_ids = list(dict.fromkeys(dependency_ids))
        if task_id in unique_ids:
            raise ValueError("self dependency is not allowed")
        for dep_id in unique_ids:
            dep_node = self.nodes.get(dep_id)
            if dep_node is None:
                raise KeyError(dep_id)
            if self._has_dependent_path(task_id, dep_id):
                raise ValueError("cyclic dependency is not allowed")
        for dep_id in unique_ids:
            if dep_id not in node.dependencies:
                if dep_id not in task.dependencies:
                    task.dependencies.append(dep_id)
                node.dependencies.add(dep_id)
                self.nodes[dep_id].dependents.add(task_id)
                if dep_id in self.completed_tasks:
                    node.dependencies.discard(dep_id)
        if task in self.task_queue and not node.is_ready:
            task.transition_to(TaskStatus.PENDING, "waiting_dependencies")
            if task not in self.waiting_queue:
                self.waiting_queue.append(task)

    def _has_dependent_path(self, start_id: str, target_id: str) -> bool:
        seen: set[str] = set()
        stack = [start_id]
        while stack:
            current = stack.pop()
            if current == target_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            node = self.nodes.get(current)
            if node is not None:
                stack.extend(node.dependents)
        return False
    
    @property
    def pending_count(self) -> int:
        """队列中等待的任务数"""
        return len(self.task_queue)
    
    @property
    def ready_count(self) -> int:
        """就绪任务数"""
        return sum(1 for task in self.task_queue if self.nodes.get(task.task_id) and self.nodes[task.task_id].is_ready)
