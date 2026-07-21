from __future__ import annotations

from applications.incident_repair.config import ExecutionMode, IncidentRunConfig
from applications.incident_repair.execution.base import AgentExecutionRequest
from applications.incident_repair.execution.runtime import AgentRuntimeExecutionProvider


class _Client:
    def submit_task(self, *args, **kwargs):
        return {"task_id": "task1"}

    def wait_task(self, task_id, timeout_s):
        return {
            "task_id": task_id,
            "status": "SUCCESS",
            "result": {"output": "[错误] not json"},
            "attempts": [{"attempt_id": "attempt1"}],
        }


async def test_runtime_parse_failure_returns_failed_result(anyio_backend):
    provider = AgentRuntimeExecutionProvider(
        IncidentRunConfig(execution_mode=ExecutionMode.RUNTIME, run_id="r", thread_id="t", source_repo="/repo", base_commit="HEAD"),
        {"client": _Client()},
    )
    request = AgentExecutionRequest(
        run_id="r",
        thread_id="t",
        graph_node="planner",
        graph_step=0,
        role="planner",
        backend="deepseek",
        goal="plan",
        source_repo="/repo",
        base_commit="HEAD",
        idempotency_key="k",
    )

    result = await provider.execute(request)

    assert result.status == "FAILED"
    assert "invalid structured output" in result.error_message
    assert "output_prefix='[错误] not json'" in result.error_message
    assert result.runtime_task_id == "task1"
    assert result.attempt_ids == ["attempt1"]
