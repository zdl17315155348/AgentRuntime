from __future__ import annotations

import asyncio

import pytest
from pathlib import Path

from applications.incident_repair.config import ExecutionMode, IncidentRunConfig
from applications.incident_repair.execution.base import AgentExecutionRequest, AgentExecutionResult, ExecutionMetrics, ExecutionProvider
from applications.incident_repair.services.run_service import IncidentRunService
from applications.incident_repair.services.run_store import RunStore


class FakeGraphProvider(ExecutionProvider):
    def __init__(self):
        self.calls: list[AgentExecutionRequest] = []
        self.cancelled: list[str] = []

    @property
    def mode(self) -> str:
        return "direct"

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        self.calls.append(request)
        metrics = ExecutionMetrics(submit_started_at=0, execution_started_at=0, execution_finished_at=0)
        if request.role == "planner":
            return AgentExecutionResult(
                status="SUCCESS",
                structured_result={
                    "version": "1.0",
                    "summary": "plan",
                    "tasks": [
                        {"local_id": "auth", "role": "coder", "goal": "fix auth", "dependencies": []},
                        {"local_id": "orders", "role": "coder", "goal": "fix orders", "dependencies": []},
                    ],
                },
                metrics=metrics,
            )
        if request.role == "coder":
            return AgentExecutionResult(
                status="SUCCESS",
                patch_ref={
                    "task_local_id": request.task_input["local_id"],
                    "artifact_id": request.task_input["local_id"],
                    "patch_path": f"/tmp/{request.task_input['local_id']}.patch",
                    "sha256": "x",
                    "changed_files": ["app.py"],
                },
                metrics=metrics,
            )
        if request.role == "tester":
            return AgentExecutionResult(status="SUCCESS", structured_result={"returncode": 0, "passed": 1, "failed": 0, "failed_tests": [], "report_artifact_id": None}, metrics=metrics)
        if request.role == "reviewer":
            return AgentExecutionResult(status="SUCCESS", structured_result={"approved": True, "requirements_covered": ["x"], "issues": [], "artifact_id": None}, metrics=metrics)
        return AgentExecutionResult(status="SUCCESS", structured_result={"commit": "HEAD"}, metrics=metrics)

    async def cancel_run(self, run_id: str) -> None:
        self.cancelled.append(run_id)

    async def inject_fault(self, run_id: str, target: dict) -> dict:
        return {}

    async def get_execution_snapshot(self, run_id: str) -> dict:
        return {}


class _Integration:
    def integrate(self, source_repo, base_commit, patch_refs, run_id, repair_round):
        class _Result:
            status = "SUCCESS"
            workspace_path = source_repo
            integrated_commit = base_commit
            applied_artifact_ids = [str(ref.get("artifact_id") or "") for ref in patch_refs]
            changed_files = ["app.py"]
            conflict_files = []
            error = None

        result = _Result()
        result.base_commit = base_commit
        return result


@pytest.mark.anyio
async def test_langgraph_runner_joins_parallel_coders_once(tmp_path):
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.sqlite")
    provider = FakeGraphProvider()
    service = IncidentRunService(store=RunStore(tmp_path / "live"))
    service.runner.checkpoint_path = tmp_path / "checkpoints.sqlite"
    config = IncidentRunConfig(execution_mode=ExecutionMode.DIRECT, run_id="run_graph", thread_id="thread_graph", source_repo=str(Path.cwd()), base_commit="HEAD")

    result = await service.execute_run(config, "fix", {"provider": provider, "integration_service": _Integration()})

    roles = [call.role for call in provider.calls]
    assert roles.count("planner") == 1
    assert roles.count("coder") == 2
    assert roles.count("integrator") == 0
    assert roles.count("tester") == 1
    assert roles.count("reviewer") == 1
    assert result["summary"]["status"] == "SUCCESS"
    assert result["summary"]["result"]["patch_non_empty"] is True
    assert service.runner.checkpoint_path.exists()


@pytest.mark.anyio
async def test_run_service_times_out_and_cancels_provider(tmp_path):
    class _HangingRunner:
        async def run(self, state, context, on_update=None):
            await asyncio.sleep(30)

    provider = FakeGraphProvider()
    service = IncidentRunService(store=RunStore(tmp_path / "live"), runner=_HangingRunner())
    config = IncidentRunConfig(
        execution_mode=ExecutionMode.DIRECT,
        run_id="run_timeout",
        thread_id="thread_timeout",
        source_repo=str(Path.cwd()),
        base_commit="HEAD",
        workflow_timeout_s=1,
    )

    result = await service.execute_run(config, "fix", {"provider": provider, "integration_service": _Integration()})

    assert provider.cancelled == ["run_timeout"]
    assert result["summary"]["status"] == "FAILED"
    assert result["summary"]["error"] == "workflow timeout after 1s"


@pytest.mark.anyio
async def test_run_service_records_graph_node_updates(tmp_path):
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.sqlite")
    provider = FakeGraphProvider()
    service = IncidentRunService(store=RunStore(tmp_path / "live"))
    service.runner.checkpoint_path = tmp_path / "checkpoints.sqlite"
    config = IncidentRunConfig(execution_mode=ExecutionMode.DIRECT, run_id="run_events", thread_id="thread_events", source_repo=str(Path.cwd()), base_commit="HEAD")

    result = await service.execute_run(config, "fix", {"provider": provider, "integration_service": _Integration()})
    events = service.store.load_events("run_events")

    assert result["summary"]["status"] == "SUCCESS"
    assert any(event["name"] == "graph.node.updated" and event["graph_node"] == "planner" for event in events)
    assert any(event["name"] == "graph.node.updated" and event["graph_node"] == "reviewer" for event in events)
