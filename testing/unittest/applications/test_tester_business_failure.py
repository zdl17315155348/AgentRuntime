from __future__ import annotations

import pytest

from applications.incident_repair.config import ExecutionMode, IncidentRunConfig
from applications.incident_repair.execution.base import AgentExecutionRequest
from applications.incident_repair.execution.direct import DirectExecutionProvider


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
