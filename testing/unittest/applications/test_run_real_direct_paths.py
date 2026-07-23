from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_run_real_direct():
    module_path = Path("scripts/run_real_direct.py")
    scripts_dir = str(module_path.parent.resolve())
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("run_real_direct", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_direct_real_defaults_persist_roots_under_run_data(monkeypatch):
    module = _load_run_real_direct()
    monkeypatch.delenv("AGENTD_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("AGENTD_ARTIFACT_ROOT", raising=False)

    module._configure_persistent_direct_roots()

    assert Path(module.os.environ["AGENTD_WORKSPACE_ROOT"]) == module.ROOT / "run-data/workspaces"
    assert Path(module.os.environ["AGENTD_ARTIFACT_ROOT"]) == module.ROOT / "run-data/artifacts"


def test_direct_real_replaces_openEuler_runtime_defaults(monkeypatch):
    module = _load_run_real_direct()
    monkeypatch.setenv("AGENTD_WORKSPACE_ROOT", "/runtime/workspaces")
    monkeypatch.setenv("AGENTD_ARTIFACT_ROOT", "/runtime/artifacts")

    module._configure_persistent_direct_roots()

    assert Path(module.os.environ["AGENTD_WORKSPACE_ROOT"]) == module.ROOT / "run-data/workspaces"
    assert Path(module.os.environ["AGENTD_ARTIFACT_ROOT"]) == module.ROOT / "run-data/artifacts"


def test_direct_real_preserves_custom_roots(monkeypatch, tmp_path):
    module = _load_run_real_direct()
    workspace_root = tmp_path / "custom-workspaces"
    artifact_root = tmp_path / "custom-artifacts"
    monkeypatch.setenv("AGENTD_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("AGENTD_ARTIFACT_ROOT", str(artifact_root))

    module._configure_persistent_direct_roots()

    assert Path(module.os.environ["AGENTD_WORKSPACE_ROOT"]) == workspace_root
    assert Path(module.os.environ["AGENTD_ARTIFACT_ROOT"]) == artifact_root
