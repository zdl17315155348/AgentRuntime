from __future__ import annotations

from pathlib import Path

import pytest

from applications.incident_repair.config import ExecutionMode, IncidentRunConfig
from applications.incident_repair.execution.base import AgentExecutionRequest, AgentExecutionResult, ExecutionMetrics, ExecutionProvider
from applications.incident_repair.services.run_service import IncidentRunService
from applications.incident_repair.services.run_store import RunStore


class _Provider(ExecutionProvider):
    def __init__(self):
        self.calls: list[AgentExecutionRequest] = []

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
                        {"local_id": "b", "role": "coder", "goal": "fix b", "dependencies": []},
                        {"local_id": "a", "role": "coder", "goal": "fix a", "dependencies": ["b"]},
                        {"local_id": "test", "role": "tester", "goal": "test", "dependencies": ["a"]},
                        {"local_id": "review", "role": "reviewer", "goal": "review", "dependencies": ["test"]},
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
                    "sha256": "sha",
                    "changed_files": [f"{request.task_input['local_id']}.py"],
                },
                metrics=metrics,
            )
        if request.role == "tester":
            return AgentExecutionResult(
                status="SUCCESS",
                structured_result={"returncode": 0, "passed": 1, "failed": 0, "failed_tests": [], "report_artifact_id": None},
                metrics=metrics,
            )
        if request.role == "reviewer":
            return AgentExecutionResult(
                status="SUCCESS",
                structured_result={"approved": True, "requirements_covered": ["x"], "issues": [], "artifact_id": None},
                metrics=metrics,
            )
        raise AssertionError(f"unexpected role {request.role}")

    async def cancel_run(self, run_id: str) -> None:
        return None

    async def inject_fault(self, run_id: str, target: dict) -> dict:
        return {}

    async def get_execution_snapshot(self, run_id: str) -> dict:
        return {}


class _Integration:
    def integrate(self, source_repo, base_commit, patch_refs, run_id, repair_round):
        class _Result:
            status = "SUCCESS"
            workspace_path = source_repo
            conflict_files = []
            error = None

        result = _Result()
        result.base_commit = base_commit
        result.applied_artifact_ids = [str(ref.get("artifact_id") or "") for ref in patch_refs]
        result.changed_files = [path for ref in patch_refs for path in ref.get("changed_files", [])]
        result.integrated_commit = f"{base_commit}-{result.applied_artifact_ids[0]}"
        return result


@pytest.mark.anyio
async def test_incident_workflow_runs_dependent_coders_sequentially(tmp_path):
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.sqlite")
    provider = _Provider()
    service = IncidentRunService(store=RunStore(tmp_path / "live"))
    service.runner.checkpoint_path = tmp_path / "checkpoints.sqlite"
    config = IncidentRunConfig(
        execution_mode=ExecutionMode.DIRECT,
        run_id="run_seq",
        thread_id="thread_seq",
        source_repo=str(Path.cwd()),
        base_commit="base0",
    )

    result = await service.execute_run(config, "fix", {"provider": provider, "integration_service": _Integration()})

    coder_calls = [call for call in provider.calls if call.role == "coder"]
    assert [call.task_input["local_id"] for call in coder_calls] == ["b", "a"]
    assert [call.base_commit for call in coder_calls] == ["base0", "base0-b"]
    assert result["state"]["completed_coder_task_ids"] == ["a", "b"]
    assert result["state"]["coder_integration_history"] == [
        {"task_id": "b", "base_commit": "base0", "integrated_commit": "base0-b", "changed_files": ["b.py"]},
        {"task_id": "a", "base_commit": "base0-b", "integrated_commit": "base0-b-a", "changed_files": ["a.py"]},
    ]
    assert result["summary"]["status"] == "SUCCESS"
