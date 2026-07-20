import os
import sys

import pytest

from aruntime.backends.base import BackendExecutionRequest
from aruntime.backends.codex_cli import CodexCLIBackend
from aruntime.core.models import AgentBackendConfig, AgentBackendType, WorkspaceSpec
from aruntime.workspace.artifact_store import ArtifactStore


@pytest.mark.anyio
async def test_codex_timeout_terminates_process(tmp_path, monkeypatch):
    fake = os.path.abspath("testing/fixtures/fake_codex.py")
    monkeypatch.setenv("FAKE_CODEX_MODE", "timeout")
    backend = CodexCLIBackend(
        AgentBackendConfig(type=AgentBackendType.CODEX_CLI, executable=sys.executable, timeout_s=1),
        {"artifact_store": ArtifactStore(str(tmp_path / "artifacts"))},
    )
    req = BackendExecutionRequest(
        task_id="t1",
        attempt_id="a1",
        agent_name="coder",
        user_message=fake,
        workspace=WorkspaceSpec(source_repo=str(tmp_path), workspace_path=str(tmp_path)),
        timeout_s=1,
    )
    backend.build_command = lambda request: [sys.executable, fake, "--output-last-message", str(tmp_path / "final.json")]

    events = []

    async def emit(event):
        events.append(event)

    try:
        result = await backend.execute(req, emit)
        assert result.status == "TIMEOUT"
        assert result.backend_pid is not None
    finally:
        monkeypatch.delenv("FAKE_CODEX_MODE", raising=False)
