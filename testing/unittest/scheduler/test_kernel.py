from aruntime.core.models import FailurePolicy, TaskSpec, TaskStatus
from aruntime.scheduler.kernel import KernelScheduler


def test_kernel_scheduler_uses_ready_and_running_queues():
    scheduler = KernelScheduler()
    task = TaskSpec(task_id="t1", agent_name="agent1", task_input={})

    scheduler.enqueue(task)

    assert scheduler.queue_snapshot()["ready"] == ["t1"]
    assert scheduler.pending_count == 1

    dequeued = scheduler.dequeue()

    assert dequeued is task
    assert task.status == TaskStatus.RUNNING
    assert scheduler.queue_snapshot()["running"] == ["t1"]
    assert scheduler.pending_count == 0

    scheduler.complete_task("t1")
    assert scheduler.queue_snapshot()["running"] == []


def test_kernel_scheduler_waits_for_dependencies_then_wakes_ready():
    scheduler = KernelScheduler()
    task1 = TaskSpec(task_id="t1", agent_name="agent1", task_input={})
    task2 = TaskSpec(task_id="t2", agent_name="agent2", task_input={}, dependencies=["t1"])

    scheduler.enqueue(task1)
    scheduler.enqueue(task2)

    assert scheduler.queue_snapshot()["ready"] == ["t1"]
    assert scheduler.queue_snapshot()["waiting"] == ["t2"]

    scheduler.dequeue()
    assert scheduler.dequeue() is None

    scheduler.complete_task("t1")

    assert scheduler.queue_snapshot()["ready"] == ["t2"]
    assert scheduler.queue_snapshot()["waiting"] == []


def test_kernel_scheduler_orders_ready_queue_by_priority():
    scheduler = KernelScheduler()
    low = TaskSpec(task_id="low", agent_name="agent1", task_input={}, priority=1)
    high = TaskSpec(task_id="high", agent_name="agent2", task_input={}, priority=10)

    scheduler.enqueue(low)
    scheduler.enqueue(high)

    assert scheduler.queue_snapshot()["ready"] == ["high", "low"]
    assert scheduler.dequeue().task_id == "high"


def test_kernel_scheduler_tracks_blocked_queue():
    scheduler = KernelScheduler()
    task = TaskSpec(task_id="t1", agent_name="agent1", task_input={})

    scheduler.enqueue(task)
    scheduler.block_task(task)

    assert scheduler.queue_snapshot()["ready"] == []
    assert scheduler.queue_snapshot()["blocked"] == ["t1"]
    assert scheduler.blocked_count == 1

    assert scheduler.wake_blocked("t1") is True
    assert scheduler.queue_snapshot()["ready"] == ["t1"]
    assert scheduler.queue_snapshot()["blocked"] == []


def test_kernel_scheduler_failure_is_isolated_by_default():
    scheduler = KernelScheduler()
    task1 = TaskSpec(task_id="t1", agent_name="agent1", task_input={})
    task2 = TaskSpec(task_id="t2", agent_name="agent2", task_input={}, dependencies=["t1"])

    scheduler.enqueue(task1)
    scheduler.enqueue(task2)
    scheduler.dequeue()
    scheduler.fail_task("t1")

    assert "t1" in scheduler.failed_tasks
    assert "t2" not in scheduler.failed_tasks
    assert task2.status == TaskStatus.PENDING
    assert scheduler.queue_snapshot()["waiting"] == ["t2"]


def test_kernel_scheduler_fail_closed_cascades_failure():
    scheduler = KernelScheduler()
    task1 = TaskSpec(
        task_id="t1",
        agent_name="agent1",
        task_input={},
        failure_policy=FailurePolicy.FAIL_CLOSED,
    )
    task2 = TaskSpec(task_id="t2", agent_name="agent2", task_input={}, dependencies=["t1"])

    scheduler.enqueue(task1)
    scheduler.enqueue(task2)
    scheduler.dequeue()
    scheduler.fail_task("t1")

    assert task2.status == TaskStatus.FAILED
    assert "t2" in scheduler.failed_tasks
    assert scheduler.queue_snapshot()["waiting"] == []
