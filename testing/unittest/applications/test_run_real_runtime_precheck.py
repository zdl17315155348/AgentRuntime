from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_run_real_runtime():
    module_path = Path("scripts/run_real_runtime.py")
    scripts_dir = str(module_path.parent.resolve())
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("run_real_runtime", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_require_real_rejects_mock_agentd(monkeypatch, tmp_path, capsys, anyio_backend):
    module = _load_run_real_runtime()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek")
    monkeypatch.setenv("CODEX_API_KEY", "codex")
    monkeypatch.setattr(module, "_wait_agentd", lambda base_url: True)
    monkeypatch.setattr(
        module,
        "_agentd_runtime_config",
        lambda base_url: {"llm_backend": "mock", "llm_api_key_present": True},
    )

    rc = await module._run(
        repo=Path("examples/production_incident_demo/target_repo"),
        require_real=True,
        base_url="http://127.0.0.1:8234",
        max_concurrency=1,
        max_repair_rounds=2,
        task_timeout_s=900,
        workflow_timeout_s=3600,
        evidence_dir=tmp_path,
    )

    assert rc == 1
    assert "agentd is using mock LLM backend" in capsys.readouterr().out
