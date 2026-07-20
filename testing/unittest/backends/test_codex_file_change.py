import os
import subprocess
import sys

import pytest

from aruntime.backends.base import BackendExecutionRequest
from aruntime.backends.codex_cli import CodexCLIBackend
from aruntime.core.models import AgentBackendConfig, AgentBackendType, WorkspaceSpec
from aruntime.workspace.artifact_store import ArtifactStore
from aruntime.workspace.manager import WorkspaceManager


def init_repo(path):
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    (path / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


@pytest.mark.anyio
async def test_codex_fake_file_change_produces_git_patch(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    init_repo(repo)
    store = ArtifactStore(str(tmp_path / "artifacts"))
    manager = WorkspaceManager(str(tmp_path / "workspaces"), store)
    workspace = manager.create_attempt_workspace(str(repo), "task", "attempt-1", "HEAD", False)
    fake = os.path.abspath("testing/fixtures/fake_codex.py")
    monkeypatch.setenv("FAKE_CODEX_MODE", "file_change")
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    backend = CodexCLIBackend(
        AgentBackendConfig(type=AgentBackendType.CODEX_CLI, executable=sys.executable, timeout_s=5),
        {"artifact_store": store},
    )
    req = BackendExecutionRequest(
        task_id="task",
        attempt_id="attempt-1",
        agent_name="coder",
        user_message="fix",
        workspace=WorkspaceSpec(**workspace.model_dump()),
        timeout_s=5,
    )
    backend.build_command = lambda request: [sys.executable, fake, "--output-last-message", str(tmp_path / "final.json")]

    async def emit(event):
        return None

    result = await backend.execute(req, emit)
    artifact = manager.create_patch_artifact(workspace, "task", "attempt-1", "root")

    assert result.status == "SUCCESS"
    assert artifact is not None
    assert artifact.metadata["changed_files"] == ["fake_change.txt"]
