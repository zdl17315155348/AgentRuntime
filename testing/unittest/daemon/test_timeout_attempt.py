import pytest

from aruntime.core.models import TaskAttempt, TaskSpec


def test_task_attempt_records_timeout_status():
    task = TaskSpec(task_id="timeout_task", agent_name="coder", task_input={})
    attempt = task.create_attempt("coder")
    task.finish_attempt(attempt, failure_reason="task timeout")
    attempt.status = "TIMEOUT"

    assert task.attempts[0].attempt_id == "timeout_task:attempt:1"
    assert task.attempts[0].status == "TIMEOUT"
    assert task.attempts[0].failure_reason == "task timeout"
