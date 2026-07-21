from __future__ import annotations

from pathlib import Path

from scripts.preflight_openeuler import _codex_config_path


def test_preflight_codex_config_uses_codex_home(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))

    assert _codex_config_path() == tmp_path / "config.toml"


def test_preflight_codex_config_defaults_to_home(monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)

    assert _codex_config_path() == Path.home() / ".codex" / "config.toml"
