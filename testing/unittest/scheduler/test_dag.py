"""
DAG 调度器单元测试
"""

import pytest
from aruntime.core.models import FailurePolicy, TaskSpec, TaskStatus
from aruntime.scheduler.dag import DAGScheduler


def test_dag_basic_enqueue_dequeue():
    """测试基本的入队和出队"""
    scheduler = DAGScheduler()
    
    task1 = TaskSpec(task_id="task1", agent_name="agent1", task_input={"msg": "test1"})
    task2 = TaskSpec(task_id="task2", agent_name="agent2", task_input={"msg": "test2"})
    
    scheduler.enqueue(task1)
    scheduler.enqueue(task2)
    
    assert scheduler.pending_count == 2
    
    # 出队应该先得到 task1
    dequeued = scheduler.dequeue()
    assert dequeued is not None
    assert dequeued.task_id == "task1"
    assert dequeued.status == TaskStatus.RUNNING
    
    # 标记 task1 完成
    scheduler.complete_task("task1")
    
    # 再出队得到 task2
    dequeued = scheduler.dequeue()
    assert dequeued is not None
    assert dequeued.task_id == "task2"


def test_dag_dependency():
    """测试任务依赖关系"""
    scheduler = DAGScheduler()
    
    # task2 依赖 task1
    task1 = TaskSpec(task_id="task1", agent_name="agent1", task_input={})
    task2 = TaskSpec(task_id="task2", agent_name="agent2", task_input={}, dependencies=["task1"])
    
    scheduler.enqueue(task1)
    scheduler.enqueue(task2)
    
    # task2 还未就绪（因为 task1 没完成）
    dequeued = scheduler.dequeue()
    assert dequeued is not None
    assert dequeued.task_id == "task1"
    
    # 再次出队，应该没有就绪任务（task2 依赖 task1）
    dequeued = scheduler.dequeue()
    assert dequeued is None
    
    # 标记 task1 完成
    scheduler.complete_task("task1")
    
    # 现在 task2 可以出队了
    dequeued = scheduler.dequeue()
    assert dequeued is not None
    assert dequeued.task_id == "task2"


def test_dag_multiple_dependencies():
    """测试多依赖任务"""
    scheduler = DAGScheduler()
    
    task1 = TaskSpec(task_id="task1", agent_name="agent1", task_input={})
    task2 = TaskSpec(task_id="task2", agent_name="agent2", task_input={})
    task3 = TaskSpec(task_id="task3", agent_name="agent3", task_input={}, dependencies=["task1", "task2"])
    
    scheduler.enqueue(task1)
    scheduler.enqueue(task2)
    scheduler.enqueue(task3)
    
    # 先执行 task1 和 task2
    scheduler.dequeue()  # task1
    scheduler.dequeue()  # task2
    
    # 完成 task1，但 task2 还没完成，task3 还不能执行
    scheduler.complete_task("task1")
    dequeued = scheduler.dequeue()
    assert dequeued is None
    
    # 完成 task2，现在 task3 可以执行了
    scheduler.complete_task("task2")
    dequeued = scheduler.dequeue()
    assert dequeued is not None
    assert dequeued.task_id == "task3"


def test_dag_failure_is_isolated_by_default():
    """默认失败隔离，不级联失败下游任务"""
    scheduler = DAGScheduler()
    
    task1 = TaskSpec(task_id="task1", agent_name="agent1", task_input={})
    task2 = TaskSpec(task_id="task2", agent_name="agent2", task_input={}, dependencies=["task1"])
    
    scheduler.enqueue(task1)
    scheduler.enqueue(task2)
    
    # 执行 task1 然后失败
    scheduler.dequeue()
    scheduler.fail_task("task1")
    
    assert "task1" in scheduler.failed_tasks
    assert "task2" not in scheduler.failed_tasks
    assert task2.status == TaskStatus.PENDING


def test_dag_fail_closed_cascades_failure():
    """显式 fail-closed 时级联失败"""
    scheduler = DAGScheduler()

    task1 = TaskSpec(
        task_id="task1",
        agent_name="agent1",
        task_input={},
        failure_policy=FailurePolicy.FAIL_CLOSED,
    )
    task2 = TaskSpec(task_id="task2", agent_name="agent2", task_input={}, dependencies=["task1"])

    scheduler.enqueue(task1)
    scheduler.enqueue(task2)
    scheduler.dequeue()
    scheduler.fail_task("task1")

    assert "task2" in scheduler.failed_tasks
    assert task2.status == TaskStatus.FAILED


def test_dag_topological_sort():
    """测试拓扑排序"""
    scheduler = DAGScheduler()
    
    # A -> B -> C
    task_a = TaskSpec(task_id="A", agent_name="agent", task_input={})
    task_b = TaskSpec(task_id="B", agent_name="agent", task_input={}, dependencies=["A"])
    task_c = TaskSpec(task_id="C", agent_name="agent", task_input={}, dependencies=["B"])
    
    scheduler.enqueue(task_a)
    scheduler.enqueue(task_b)
    scheduler.enqueue(task_c)
    
    order = scheduler.topological_sort()
    assert order == ["A", "B", "C"]


def test_dag_cyclic_dependency():
    """测试循环依赖检测"""
    scheduler = DAGScheduler()
    
    # A -> B -> A (循环)
    task_a = TaskSpec(task_id="A", agent_name="agent", task_input={}, dependencies=["B"])
    task_b = TaskSpec(task_id="B", agent_name="agent", task_input={}, dependencies=["A"])
    
    scheduler.enqueue(task_a)
    scheduler.enqueue(task_b)
    
    with pytest.raises(ValueError, match="循环依赖"):
        scheduler.topological_sort()


def test_dag_dynamic_task():
    """测试动态任务添加"""
    scheduler = DAGScheduler()
    
    task1 = TaskSpec(task_id="task1", agent_name="agent1", task_input={})
    scheduler.enqueue(task1)
    
    # 动态添加依赖 task1 的任务
    task2 = TaskSpec(task_id="task2", agent_name="agent2", task_input={})
    scheduler.add_dynamic_task(task2, parent_task_id="task1")
    
    # 先执行 task1
    dequeued = scheduler.dequeue()
    assert dequeued.task_id == "task1"
    
    scheduler.complete_task("task1")
    
    # 现在 task2 可以执行了
    dequeued = scheduler.dequeue()
    assert dequeued is not None
    assert dequeued.task_id == "task2"


def test_dag_ready_count():
    """测试就绪任务计数"""
    scheduler = DAGScheduler()
    
    task1 = TaskSpec(task_id="task1", agent_name="agent1", task_input={})
    task2 = TaskSpec(task_id="task2", agent_name="agent2", task_input={}, dependencies=["task1"])
    
    scheduler.enqueue(task1)
    scheduler.enqueue(task2)
    
    # 只有 task1 就绪
    assert scheduler.ready_count == 1
    
    scheduler.dequeue()
    scheduler.complete_task("task1")
    
    # 现在 task2 也就绪了
    assert scheduler.ready_count == 1
