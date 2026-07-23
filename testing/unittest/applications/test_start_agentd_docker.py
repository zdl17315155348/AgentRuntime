from __future__ import annotations

from pathlib import Path


def test_start_agentd_docker_mounts_codex_config():
    script = Path("scripts/start_agentd_docker.sh").read_text(encoding="utf-8")

    assert "CODEX_HOME_MOUNT" in script
    assert "/root/.codex/config.toml:ro" in script
    assert '"${CODEX_HOME_MOUNT[@]}"' in script
    assert "--init" in script


def test_test_docker_openeuler_uses_init_for_child_reaping():
    script = Path("scripts/test_docker_openeuler.sh").read_text(encoding="utf-8")

    assert "--init" in script
