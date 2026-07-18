from aruntime.core.models import TaskSpec, TaskStatus
from aruntime.daemon.recovery_service import recover_tasks
from aruntime.daemon.store import SQLiteStateStore
from aruntime.resource.types import ResourceLease, ResourceRequest


def test_daemon_restart_recovers_running_and_preserves_success_waiting(tmp_path):
    store = SQLiteStateStore(str(tmp_path / "state.db"))
    task_a = TaskSpec(task_id="A", agent_name="agent", task_input={})
    task_a.transition_to(TaskStatus.READY, "test")
    task_a.transition_to(TaskStatus.RUNNING, "dispatch")
    task_a.transition_to(TaskStatus.SUCCESS, "done")
    task_b = TaskSpec(task_id="B", agent_name="agent", task_input={})
    task_b.transition_to(TaskStatus.READY, "test")
    task_b.transition_to(TaskStatus.RUNNING, "dispatch")
    task_c = TaskSpec(task_id="C", agent_name="agent", task_input={}, dependencies=["B"])
    task_c.transition_to(TaskStatus.PENDING, "waiting_dependencies")
    store.save_task(task_a)
    store.save_task(task_b)
    store.save_task(task_c)
    store.save_lease(ResourceLease(task_id="B", agent_name="agent", request=ResourceRequest()))

    recovered, decisions = recover_tasks(store)

    assert decisions["B"] == "RUNNING->ORPHANED->READY"
    assert "A" not in decisions
    assert any(task.task_id == "B" and task.status == TaskStatus.READY for task in recovered)
    rows = store.load_tasks()
    states = {row["task_id"]: row["state"] for row in rows}
    assert states["A"] == "SUCCESS"
    assert states["B"] == "READY"
    assert states["C"] == "PENDING"
    assert store.counts()["resource_leases"] == 1
