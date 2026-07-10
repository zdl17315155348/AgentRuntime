import json

from aruntime.core.models import AgentSpec, TaskSpec, TaskStatus
from aruntime.daemon.recovery_service import recover_tasks
from aruntime.daemon.store import SQLiteStateStore


def test_sqlite_store_wal_persists_agents_tasks_and_recovery(tmp_path):
    store = SQLiteStateStore(str(tmp_path / "state.db"))
    agent = AgentSpec(agent_name="agent_a", role="tester")
    task = TaskSpec(agent_name="agent_a", task_input={"request": "x"})
    task.transition_to(TaskStatus.READY, "test")
    task.transition_to(TaskStatus.RUNNING, "dispatch")

    store.save_agent(agent, worker_pid=123, auth_token="token")
    store.save_task(task)

    store2 = SQLiteStateStore(str(tmp_path / "state.db"))
    agents = store2.load_agents()
    assert agents[0]["agent_name"] == "agent_a"
    assert agents[0]["auth_token"] == "token"

    recovered, decisions = recover_tasks(store2)
    assert [t.task_id for t in recovered] == [task.task_id]
    assert decisions[task.task_id] == "RUNNING->ORPHANED->READY"

    stored = json.loads(store2.load_tasks()[0]["data"])
    assert stored["status"] == "READY"
    assert stored["tcb"]["state"] == "READY"


def test_store_counts_trace_events(tmp_path):
    store = SQLiteStateStore(str(tmp_path / "state.db"))
    store.save_trace_event("trace_1", "task_1", "task.created", {"agent_name": "a"})
    counts = store.counts()
    assert counts["trace_events"] == 1
