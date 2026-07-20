from __future__ import annotations

import pytest

from applications.incident_repair.config import ExecutionMode, IncidentRunConfig
from applications.incident_repair.execution.base import AgentExecutionRequest, AgentExecutionResult, ExecutionMetrics
from applications.incident_repair.execution.direct import DirectExecutionProvider
from applications.incident_repair.execution.factory import create_execution_provider


def _config(mode: ExecutionMode = ExecutionMode.DIRECT) -> IncidentRunConfig:
    return IncidentRunConfig(
        execution_mode=mode,
        run_id="run1",
        thread_id="thread1",
        source_repo=".",
        base_commit="HEAD",
        max_concurrency=1,
    )


def _request(backend: str = "deepseek", role: str = "planner") -> AgentExecutionRequest:
    return AgentExecutionRequest(
        run_id="run1",
        thread_id="thread1",
        graph_node=role,
        graph_step=0,
        role=role,
        backend=backend,
        goal="fix auth",
        source_repo=".",
        base_commit="HEAD",
        idempotency_key="idem",
    )


@pytest.mark.anyio
async def test_direct_provider_returns_common_result_shape_for_planner():
    provider = DirectExecutionProvider(_config())
    result = await provider.execute(_request())

    assert isinstance(result, AgentExecutionResult)
    assert result.status == "SUCCESS"
    assert result.structured_result["tasks"][0]["role"] == "coder"
    assert result.metrics.total_ms >= 0


def test_provider_factory_switches_modes():
    assert create_execution_provider(_config(ExecutionMode.DIRECT)).mode == "direct"
    assert create_execution_provider(_config(ExecutionMode.REPLAY)).mode == "replay"


class _FakeClient:
    def __init__(self):
        self.submitted = None

    def submit_task(self, agent_name, task_input, **kwargs):
        self.submitted = {"agent_name": agent_name, "task_input": task_input, **kwargs}
        return {"task_id": "t1", "status": "PENDING"}

    def wait_task(self, task_id, timeout_s):
        return {
            "task_id": task_id,
            "status": "SUCCESS",
            "result": {"output": {"returncode": 0, "passed": 1, "failed": 0, "failed_tests": [], "report_artifact_id": None}},
            "attempts": [{"attempt_id": "a1"}],
            "scheduler": {"queue_wait_ms": 3},
        }


@pytest.mark.anyio
async def test_runtime_provider_reuses_client_and_maps_request_fields():
    provider = create_execution_provider(_config(ExecutionMode.RUNTIME), {"client": _FakeClient()})
    result = await provider.execute(_request("direct_tool", "tester"))

    client = provider.client
    assert client.submitted["required_backend"] == "direct_tool"
    assert client.submitted["task_role"] == "tester"
    assert client.submitted["idempotency_key"] == "idem"
    assert client.submitted["task_input"]["graph"]["node"] == "tester"
    assert result.status == "SUCCESS"
    assert result.runtime_task_id == "t1"
    assert result.structured_result["returncode"] == 0
    assert client.submitted["task_input"]["graph_managed"] is True


class _PlannerClient(_FakeClient):
    def wait_task(self, task_id, timeout_s):
        return {
            "task_id": task_id,
            "status": "SUCCESS",
            "result": {
                "output": '{"inspection": {}, "plan": {"version": "1.0", "summary": "p", "tasks": [{"local_id": "c", "role": "coder", "goal": "g", "dependencies": []}]}}'
            },
            "attempts": [{"attempt_id": "a1"}],
            "scheduler": {},
        }


@pytest.mark.anyio
async def test_runtime_provider_returns_planner_plan_without_runtime_dag_materialization():
    provider = create_execution_provider(_config(ExecutionMode.RUNTIME), {"client": _PlannerClient()})
    result = await provider.execute(_request("deepseek", "planner"))

    assert provider.client.submitted["task_input"]["graph_managed"] is True
    assert result.structured_result["tasks"][0]["local_id"] == "c"
