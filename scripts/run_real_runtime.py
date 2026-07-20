from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aruntime.api.client import AgentRuntimeClient
from applications.incident_repair.config import ExecutionMode, IncidentRunConfig
from applications.incident_repair.services.run_service import IncidentRunService, register_demo_agents


DEFAULT_REPO = ROOT / "examples/production_incident_demo/target_repo"


def _base_commit(repo: Path) -> str:
    proc = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else "HEAD"


def _wait_agentd(base_url: str) -> bool:
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if httpx.get(f"{base_url}/metrics", timeout=1, trust_env=False).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


async def _run(repo: Path, require_real: bool, base_url: str) -> int:
    if require_real and not (os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY")):
        print("[FAIL] missing DEEPSEEK_API_KEY or LLM_API_KEY")
        return 1
    if require_real and not (os.getenv("OPENAI_API_KEY") or os.getenv("CODEX_API_KEY")):
        print("[FAIL] missing OPENAI_API_KEY or CODEX_API_KEY")
        return 1
    if not require_real and (not (os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY")) or not (os.getenv("OPENAI_API_KEY") or os.getenv("CODEX_API_KEY"))):
        print("[SKIP] real Runtime E2E requires DeepSeek and Codex keys")
        return 0
    if not os.getenv("LLM_API_KEY") and os.getenv("DEEPSEEK_API_KEY"):
        os.environ["LLM_API_KEY"] = os.environ["DEEPSEEK_API_KEY"]
    if not os.getenv("CODEX_API_KEY") and os.getenv("OPENAI_API_KEY"):
        os.environ["CODEX_API_KEY"] = os.environ["OPENAI_API_KEY"]
    if not _wait_agentd(base_url):
        print(f"[FAIL] agentd not ready at {base_url}")
        return 1

    client = AgentRuntimeClient(base_url)
    register_demo_agents(client)
    config = IncidentRunConfig(
        execution_mode=ExecutionMode.RUNTIME,
        run_id=f"runtime_real_{uuid4().hex[:12]}",
        thread_id=f"thread_{uuid4().hex[:12]}",
        source_repo=str(repo),
        base_commit=_base_commit(repo),
        max_concurrency=2,
        max_repair_rounds=1,
        fault_mode=False,
    )
    result = await IncidentRunService().execute_run(config, "修复认证、JWT和订单安全问题", {"client": client})
    summary = result["summary"]
    out_dir = Path("run-data/live") / config.run_id
    (out_dir / "e2e_evidence.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"run_id": config.run_id, "mode": "runtime", "status": summary.get("status"), "summary": str(out_dir / "summary.json")}, ensure_ascii=False))
    return 0 if summary.get("status") == "SUCCESS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", default=str(DEFAULT_REPO))
    parser.add_argument("--base-url", default=os.getenv("AGENTD_BASE_URL", "http://127.0.0.1:8234"))
    parser.add_argument("--require-real", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_run(Path(args.source_repo).resolve(), args.require_real, args.base_url))


if __name__ == "__main__":
    raise SystemExit(main())
