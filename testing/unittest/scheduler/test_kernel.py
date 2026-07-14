from aruntime.core.models import FailureMode, FailurePolicy, TaskSpec, TaskStatus
from aruntime.scheduler.kernel import KernelScheduler
from datetime import datetime, timedelta


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


def test_kernel_scheduler_records_completed_and_runtime_metadata():
    scheduler = KernelScheduler(policy="fifo")
    task = TaskSpec(task_id="t1", agent_name="agent1", task_input={})

    scheduler.enqueue(task)
    assert scheduler.dispatch_ready() == [task]

    assert task.started_at is not None
    assert task.queue_wait_ms is not None
    assert task.scheduler_decision_reason == "fifo_order"

    scheduler.complete_task("t1")
    snapshot = scheduler.queue_snapshot()
    assert snapshot["running"] == []
    assert snapshot["completed"] == ["t1"]


def test_kernel_scheduler_moves_resource_blocked_task_to_waiting_then_wakes():
    calls = {"count": 0}

    def checker(task):
        calls["count"] += 1
        if calls["count"] == 1:
            return False, "cpu_busy"
        return True, "resource_available"

    scheduler = KernelScheduler(policy="resource_aware", resource_checker=checker)
    task = TaskSpec(task_id="t1", agent_name="agent1", task_input={})

    scheduler.enqueue(task)
    assert scheduler.dispatch_ready() == []
    assert scheduler.queue_snapshot()["waiting"] == ["t1"]
    assert scheduler.queue_snapshot()["blocked"] == ["t1"]
    assert task.resource_block_reason == "cpu_busy"

    assert scheduler.dispatch_ready() == [task]
    assert scheduler.queue_snapshot()["waiting"] == []
    assert task.resource_block_reason == ""


def test_kernel_scheduler_keeps_resource_blocked_task_waiting_until_resources_available():
    calls = {"count": 0}

    def checker(task):
        calls["count"] += 1
        if calls["count"] < 3:
            return False, "cpu_busy"
        return True, "resource_available"

    scheduler = KernelScheduler(policy="resource_aware", resource_checker=checker)
    task = TaskSpec(task_id="t1", agent_name="agent1", task_input={})

    scheduler.enqueue(task)
    assert scheduler.dispatch_ready() == []
    scheduler.wake_waiting()

    assert scheduler.queue_snapshot()["ready"] == []
    assert scheduler.queue_snapshot()["waiting"] == ["t1"]
    assert task.resource_block_reason == "cpu_busy"

    assert scheduler.dispatch_ready() == [task]


def test_kernel_scheduler_default_fail_open_releases_dependent_task():
    scheduler = KernelScheduler()
    task1 = TaskSpec(
        task_id="t1",
        agent_name="agent1",
        task_input={},
        failure_policy={"mode": "fail_open"},
    )
    task2 = TaskSpec(task_id="t2", agent_name="agent2", task_input={}, dependencies=["t1"])

    scheduler.enqueue(task1)
    scheduler.enqueue(task2)
    scheduler.dequeue()
    scheduler.fail_task("t1")

    assert "t2" not in scheduler.failed_tasks
    assert scheduler.queue_snapshot()["ready"] == ["t2"]


def test_kernel_scheduler_resource_aware_score_uses_normalized_ratios():
    scheduler = KernelScheduler(policy="resource_aware", resource_checker=lambda task: (True, "resource_available"))
    low_ratio = TaskSpec(
        task_id="low_ratio",
        agent_name="agent1",
        task_input={},
        resource_request={"memory_max_bytes": 100_000_000, "token_budget": 100, "llm_max_concurrent": 1},
    )
    balanced_heavy = TaskSpec(
        task_id="balanced",
        agent_name="agent1",
        task_input={},
        resource_request={"memory_max_bytes": 90_000_000, "token_budget": 10_000, "llm_max_concurrent": 10},
    )

    scheduler.enqueue(low_ratio)
    scheduler.enqueue(balanced_heavy)
    dispatched = scheduler.dispatch_ready(limit=2)

    assert [task.task_id for task in dispatched] == ["low_ratio", "balanced"]
    assert '"memory_ratio"' in low_ratio.scheduler_decision_reason
    assert '"token_ratio"' in low_ratio.scheduler_decision_reason
    assert '"llm_ratio"' in low_ratio.scheduler_decision_reason
    assert '"final_score"' in low_ratio.scheduler_decision_reason


def test_kernel_scheduler_policy_plugins_order_tasks():
    low = TaskSpec(task_id="low", agent_name="agent1", task_input={}, priority=1)
    high = TaskSpec(task_id="high", agent_name="agent1", task_input={}, priority=10)
    priority_scheduler = KernelScheduler(policy="priority")
    priority_scheduler.enqueue(low)
    priority_scheduler.enqueue(high)
    assert priority_scheduler.dequeue().task_id == "high"

    late = TaskSpec(
        task_id="late",
        agent_name="agent1",
        task_input={},
        deadline=datetime.now() + timedelta(hours=2),
    )
    soon = TaskSpec(
        task_id="soon",
        agent_name="agent1",
        task_input={},
        deadline=datetime.now() + timedelta(minutes=1),
    )
    deadline_scheduler = KernelScheduler(policy="deadline")
    deadline_scheduler.enqueue(late)
    deadline_scheduler.enqueue(soon)
    assert deadline_scheduler.dequeue().task_id == "soon"


def test_kernel_scheduler_fair_share_prefers_less_dispatched_agent():
    scheduler = KernelScheduler(policy="fair_share")
    a1_first = TaskSpec(task_id="a1_first", agent_name="a1", task_input={})
    a1_second = TaskSpec(task_id="a1_second", agent_name="a1", task_input={})
    a2_first = TaskSpec(task_id="a2_first", agent_name="a2", task_input={})

    scheduler.enqueue(a1_first)
    assert scheduler.dequeue().task_id == "a1_first"
    scheduler.enqueue(a1_second)
    scheduler.enqueue(a2_first)

    assert scheduler.dequeue().task_id == "a2_first"


def test_kernel_scheduler_edge_fail_open_releases_dependent_task():
    scheduler = KernelScheduler()
    task1 = TaskSpec(
        task_id="t1",
        agent_name="agent1",
        task_input={},
        failure_policy={"mode": "fail_closed"},
    )
    task2 = TaskSpec(
        task_id="t2",
        agent_name="agent2",
        task_input={},
        dependencies=["t1"],
        dependency_failure_policies={"t1": FailureMode.FAIL_OPEN},
    )

    scheduler.enqueue(task1)
    scheduler.enqueue(task2)
    scheduler.dequeue()
    scheduler.fail_task("t1")

    assert "t2" not in scheduler.failed_tasks
    assert scheduler.queue_snapshot()["ready"] == ["t2"]
