import pytest

from aruntime.core.models import TaskSpec, TaskStatus


def test_task_spec_creates_definition_tcb_and_uuid_task_id():
    task = TaskSpec(agent_name="agent1", task_input={"x": 1}, dependencies=["dep"], priority=3)

    assert task.task_id.startswith("task_")
    assert task.definition.agent_name == "agent1"
    assert task.definition.dependencies == ["dep"]
    assert task.tcb.task_id == task.task_id
    assert task.status == TaskStatus.PENDING


def test_task_state_changes_go_through_tcb_fsm():
    task = TaskSpec(task_id="t1", agent_name="agent1", task_input={})

    task.transition_to(TaskStatus.READY, "enqueue")
    task.transition_to(TaskStatus.RUNNING, "dispatch")
    task.transition_to(TaskStatus.SUCCESS, "done")

    assert task.status == TaskStatus.SUCCESS
    assert task.tcb.state == TaskStatus.SUCCESS
    assert task.queue_wait_ms is not None
    assert task.agent_runtime_ms is not None
    with pytest.raises(ValueError):
        task.transition_to(TaskStatus.RUNNING, "invalid")


def test_task_attempt_keeps_fallback_agent_without_changing_definition():
    task = TaskSpec(task_id="t1", agent_name="primary", task_input={})

    attempt = task.create_attempt("fallback", worker_pid=123)
    task.finish_attempt(attempt, result={"output": "ok"}, token_usage={"total_tokens": 1})

    assert task.agent_name == "primary"
    assert task.definition.agent_name == "primary"
    assert task.attempts[0].agent_name == "fallback"
    assert task.attempts[0].result == {"output": "ok"}
