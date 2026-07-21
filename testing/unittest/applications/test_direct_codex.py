from applications.incident_repair.direct.codex import _is_retryable_codex_failure, _prepare_codex_home


def test_direct_codex_prepares_workspace_scoped_codex_home(tmp_path, monkeypatch):
    source = tmp_path / "source-codex"
    source.mkdir()
    (source / "config.toml").write_text("model = \"test\"\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(source))

    codex_home = _prepare_codex_home(str(workspace))

    assert codex_home == workspace / ".codex-home"
    assert codex_home != source
    assert (codex_home / "config.toml").read_text(encoding="utf-8") == "model = \"test\"\n"


def test_direct_codex_can_use_external_codex_home(tmp_path, monkeypatch):
    source = tmp_path / "source-codex"
    source.mkdir()
    (source / "config.toml").write_text("model = \"test\"\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(source))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    captured = {}

    class _Proc:
        returncode = 0
        pid = 123

        async def communicate(self):
            return b'{"type":"turn.completed","item":{"type":"agent_message","text":"done"}}\n', b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["command"] = list(args)
        captured["env_codex_home"] = kwargs["env"]["CODEX_HOME"]
        return _Proc()

    monkeypatch.setattr("applications.incident_repair.direct.codex.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    executor = __import__("applications.incident_repair.direct.codex", fromlist=["DirectCodexExecutor"]).DirectCodexExecutor(executable="codex")
    rc, stdout, stderr, pid = __import__("asyncio").run(
        executor.execute("goal", str(workspace), "coder", 1, codex_home=str(tmp_path / "artifact-codex-home"))
    )

    assert rc == 0
    assert pid == 123
    assert captured["command"][:5] == ["codex", "--ask-for-approval", "never", "exec", "--sandbox"]
    assert captured["env_codex_home"].endswith("artifact-codex-home")
    assert "agent_message" in stdout


def test_direct_codex_retries_upstream_stream_disconnect():
    assert _is_retryable_codex_failure("", "stream disconnected before completion: Upstream request failed")
    assert not _is_retryable_codex_failure("", "schema validation failed")
