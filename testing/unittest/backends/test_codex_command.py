from pathlib import Path
import asyncio

import pytest

from aruntime.backends.codex_cli import CodexCLIBackend
from aruntime.backends.base import BackendExecutionRequest
from aruntime.core.models import AgentBackendConfig, AgentBackendType, WorkspaceSpec
from aruntime.workspace.artifact_store import ArtifactStore


ROOT = Path(__file__).resolve().parents[3]


def test_codex_command_uses_safe_flags_without_cli_schema_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEX_ENABLE_OUTPUT_SCHEMA", raising=False)
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

    assert command[:5] == ["fake-codex", "--ask-for-approval", "never", "exec", "--sandbox"]
    assert "--sandbox" in command
    assert "workspace-write" in command
    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    assert "--output-schema" not in command


def test_codex_command_can_enable_cli_schema_for_probe(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_ENABLE_OUTPUT_SCHEMA", "1")
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

    assert "--output-schema" in command
    schema = command[command.index("--output-schema") + 1]
    assert schema.startswith("/")
    assert schema.endswith("schema.json")


def test_codex_prompt_pins_goal_and_attempt_workspace(tmp_path):
    source = tmp_path / "source"
    workspace = tmp_path / "attempt-worktree"
    source.mkdir()
    workspace.mkdir()
    backend = CodexCLIBackend(
        AgentBackendConfig(type=AgentBackendType.CODEX_CLI, executable="fake-codex"),
        {"artifact_store": ArtifactStore(str(tmp_path / "artifacts"))},
    )
    req = BackendExecutionRequest(
        task_id="t1",
        attempt_id="a1",
        agent_name="coder",
        user_message="fix",
        task_input={"source_repo": str(source), "goal": "fix auth"},
        workspace=WorkspaceSpec(source_repo=str(source), workspace_path=str(workspace)),
    )

    prompt = backend._build_prompt(req)

    assert "Goal:\nfix auth" in prompt
    assert f"Workspace:\n{workspace.resolve()}" in prompt
    assert "Only inspect and modify files under this workspace" in prompt
    assert "Do not edit the source repository path" in prompt


def test_codex_coder_and_repair_prompts_are_json_only():
    for name in ("coder.md", "repair.md"):
        prompt = (ROOT / "applications" / "incident_repair" / "prompts" / name).read_text(encoding="utf-8")
        assert "Return only one JSON object" in prompt
        assert "completed: boolean" in prompt
        assert "remaining_issues: array of strings" in prompt


def test_codex_backend_prepares_attempt_scoped_codex_home(tmp_path, monkeypatch):
    source = tmp_path / "source-codex"
    source.mkdir()
    (source / "config.toml").write_text("model = \"test\"\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(source))
    store = ArtifactStore(str(tmp_path / "artifacts"))
    backend = CodexCLIBackend(
        AgentBackendConfig(type=AgentBackendType.CODEX_CLI, executable="fake-codex"),
        {"artifact_store": store},
    )
    req = BackendExecutionRequest(
        task_id="t1",
        attempt_id="a1",
        agent_name="coder",
        user_message="fix",
        workspace=WorkspaceSpec(source_repo=str(tmp_path), workspace_path=str(tmp_path)),
    )

    codex_home = backend._prepare_codex_home(req)

    assert codex_home != source
    assert codex_home.name == "codex-home"
    assert (codex_home / "config.toml").read_text(encoding="utf-8") == "model = \"test\"\n"


@pytest.mark.anyio
async def test_codex_backend_closes_stdin(tmp_path, monkeypatch):
    captured = {}

    class _Process:
        pid = 123
        returncode = 0
        stdout = None
        stderr = None

        async def wait(self):
            return 0

    async def fake_create(*command, **kwargs):
        captured["stdin"] = kwargs.get("stdin")
        return _Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    backend = CodexCLIBackend(
        AgentBackendConfig(type=AgentBackendType.CODEX_CLI, executable="fake-codex"),
        {"artifact_store": ArtifactStore(str(tmp_path / "artifacts"))},
    )
    req = BackendExecutionRequest(
        task_id="t1",
        attempt_id="a1",
        agent_name="coder",
        user_message="fix",
        workspace=WorkspaceSpec(source_repo=str(tmp_path), workspace_path=str(tmp_path)),
    )

    async def emit(event):
        return None

    result = await backend.execute(req, emit)

    assert captured["stdin"] is asyncio.subprocess.DEVNULL
    assert result.status == "SUCCESS"
