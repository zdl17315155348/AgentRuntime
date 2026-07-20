from pathlib import Path

from aruntime.backends.codex_cli import CodexCLIBackend
from aruntime.backends.base import BackendExecutionRequest
from aruntime.core.models import AgentBackendConfig, AgentBackendType, WorkspaceSpec
from aruntime.workspace.artifact_store import ArtifactStore


def test_codex_command_uses_safe_flags(tmp_path):
    backend = CodexCLIBackend(
        AgentBackendConfig(type=AgentBackendType.CODEX_CLI, executable="fake-codex", sandbox="workspace-write", output_schema="schema.json"),
        {"artifact_store": ArtifactStore(str(tmp_path / "artifacts"))},
    )
    req = BackendExecutionRequest(
        task_id="t1",
        attempt_id="a1",
        agent_name="coder",
        user_message="fix",
        workspace=WorkspaceSpec(source_repo=str(tmp_path), workspace_path=str(tmp_path)),
    )

    command = backend.build_command(req)

    assert "--sandbox" in command
    assert "workspace-write" in command
    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    assert "--output-schema" in command
    schema = command[command.index("--output-schema") + 1]
    assert schema.startswith("/")
    assert schema.endswith("schema.json")
