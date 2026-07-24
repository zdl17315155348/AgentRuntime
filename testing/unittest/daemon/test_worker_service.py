from __future__ import annotations

from aruntime.daemon import worker_service


def test_start_worker_process_passes_llm_model(monkeypatch, tmp_path):
    captured = {}

    class _Proc:
        pid = 123

    def fake_popen(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return _Proc()

    monkeypatch.setenv("AGENTD_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(worker_service.subprocess, "Popen", fake_popen)

    proc = worker_service.start_worker_process("architect", "/tmp/agent.sock", "token", "deepseek", "key", "deepseek-v4-flash")

    assert proc.pid == 123
    assert captured["env"]["LLM_MODEL"] == "deepseek-v4-flash"
