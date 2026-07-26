from __future__ import annotations

import pytest

from applications.incident_repair.config import ExecutionMode, GraphRuntimeContext, IncidentRunConfig
from applications.incident_repair.execution.base import AgentExecutionRequest, AgentExecutionResult, ExecutionMetrics
from applications.incident_repair.execution.direct import DirectExecutionProvider
from applications.incident_repair.nodes.tester import tester_node as run_tester_node


class _WorkspaceManager:
    def __init__(self):
        self.created = None
        self.cleaned = None

    def create_attempt_workspace(self, source_repo, task_id, attempt_id, base_ref, read_only, root_task_id=None):
        self.created = {"source_repo": source_repo, "task_id": task_id, "attempt_id": attempt_id, "base_ref": base_ref, "read_only": read_only, "root_task_id": root_task_id}
        return type("W", (), {"workspace_path": "/tmp/test-worktree"})()

    def cleanup_workspace(self, workspace, force=False):
        self.cleaned = {"workspace_path": workspace.workspace_path, "force": force}


@pytest.mark.anyio
async def test_tester_runs_in_integrated_commit_worktree_and_keeps_pytest_failure_as_business_result(monkeypatch):
    async def fake_pytest(workspace_path, timeout_s, junit_xml="pytest.xml"):
        return {"returncode": 1, "passed": 0, "failed": 1, "failed_tests": [{"name": "t::fail", "message": "boom"}], "report_artifact_id": None}

    monkeypatch.setattr("applications.incident_repair.execution.direct.run_pytest_direct", fake_pytest)
    workspace_manager = _WorkspaceManager()
    provider = DirectExecutionProvider(
        IncidentRunConfig(execution_mode=ExecutionMode.DIRECT, run_id="run", thread_id="thread", source_repo="/repo", base_commit="HEAD"),
        {"workspace_manager": workspace_manager},
    )
    request = AgentExecutionRequest(
        run_id="run",
        thread_id="thread",
        graph_node="tester",
        graph_step=3,
        role="tester",
        backend="direct_tool",
        goal="run pytest",
        task_input={"integrated_commit": "deadbeef"},
        source_repo="/repo",
        base_commit="HEAD",
        idempotency_key="idem",
        timeout_s=30,
    )

    result = await provider.execute(request)

    assert workspace_manager.created["base_ref"] == "deadbeef"
    assert workspace_manager.created["read_only"] is True
    assert result.status == "SUCCESS"
    assert result.structured_result["returncode"] == 1
    assert workspace_manager.cleaned["force"] is True


@pytest.mark.anyio
async def test_tester_node_submits_run_pytest_tool_payload():
    class _Provider:
        mode = "runtime"

        def __init__(self):
            self.request = None

        async def execute(self, request):
            self.request = request
            metrics = ExecutionMetrics(submit_started_at=0, execution_started_at=0, execution_finished_at=0)
            return AgentExecutionResult(
                status="SUCCESS",
                structured_result={"returncode": 0, "passed": 1, "failed": 0, "failed_tests": [], "report_artifact_id": None},
                runtime_task_id="task_tester",
                metrics=metrics,
            )

    provider = _Provider()
    state = {
        "run_id": "run",
        "thread_id": "thread",
        "source_repo": "/repo",
        "base_commit": "base",
        "integrated_commit": "deadbeef",
    }

    config = IncidentRunConfig(execution_mode=ExecutionMode.RUNTIME, run_id="run", thread_id="thread", source_repo="/repo", base_commit="base")
    context = GraphRuntimeContext(provider=provider, run_config=config, event_bus=None)

    update = await run_tester_node(state, context)

    assert provider.request.task_input["integrated_commit"] == "deadbeef"
    assert provider.request.task_input["__tool"]["name"] == "run_pytest"
    assert provider.request.task_input["__tool"]["arguments"]["paths"] == ["tests"]
    assert provider.request.base_commit == "deadbeef"
    assert update["test_summary"]["returncode"] == 0


@pytest.mark.anyio
async def test_tester_node_converts_runtime_timeout_to_test_failure():
    class _Provider:
        mode = "runtime"

        async def execute(self, request):
            raise TimeoutError("task task_tester did not finish within 330s")

    state = {
        "run_id": "run",
        "thread_id": "thread",
        "source_repo": "/repo",
        "base_commit": "base",
        "integrated_commit": "deadbeef",
    }
    config = IncidentRunConfig(execution_mode=ExecutionMode.RUNTIME, run_id="run", thread_id="thread", source_repo="/repo", base_commit="base")
    context = GraphRuntimeContext(provider=_Provider(), run_config=config, event_bus=None)

    update = await run_tester_node(state, context)

    assert update["test_summary"]["returncode"] == 1
    assert update["test_summary"]["failed_tests"][0]["name"] == "runtime_tester_timeout"
