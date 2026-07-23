from __future__ import annotations

from pathlib import Path

from scripts import e2e_runtime_guard


def test_e2e_runtime_guard_rejects_python_pid1(monkeypatch, capsys):
    monkeypatch.setattr(e2e_runtime_guard.os, "getpid", lambda: 1)
    monkeypatch.delenv("ALLOW_PYTHON_PID1_E2E", raising=False)

    assert e2e_runtime_guard.reject_python_pid1_without_init() is True
    assert "docker --init" in capsys.readouterr().out


def test_e2e_runtime_guard_allows_non_pid1(monkeypatch):
    monkeypatch.setattr(e2e_runtime_guard.os, "getpid", lambda: 42)

    assert e2e_runtime_guard.reject_python_pid1_without_init() is False


def test_e2e_runtime_guard_allows_explicit_override(monkeypatch):
    monkeypatch.setattr(e2e_runtime_guard.os, "getpid", lambda: 1)
    monkeypatch.setenv("ALLOW_PYTHON_PID1_E2E", "1")

    assert e2e_runtime_guard.reject_python_pid1_without_init() is False


def test_real_e2e_scripts_install_pid1_guard():
    for script in ("scripts/run_real_direct.py", "scripts/run_real_runtime.py", "scripts/run_real_runtime_fault.py"):
        text = Path(script).read_text(encoding="utf-8")
        assert "reject_python_pid1_without_init" in text
