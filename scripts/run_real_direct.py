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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from applications.incident_repair.config import ExecutionMode, IncidentRunConfig
from applications.incident_repair.services.run_service import IncidentRunService
from prepare_e2e_repo import prepare_e2e_repo


DEFAULT_REPO = ROOT / "examples/production_incident_demo/target_repo"


def _ensure_git_safe_directory(repo: Path) -> None:
    subprocess.run(
        ["git", "config", "--global", "--add", "safe.directory", str(repo)],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )


def _git_stdout(args: list[str], cwd: Path = ROOT, timeout: int = 10) -> str:
    proc = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=False, timeout=timeout)
    return proc.stdout.strip() if proc.returncode == 0 else "HEAD"


def _source_commit() -> str:
    return _git_stdout(["git", "-c", f"safe.directory={ROOT}", "rev-parse", "HEAD"])


def _optional_stdout(args: list[str], cwd: Path = ROOT, timeout: int = 10) -> str:
    try:
        proc = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=False, timeout=timeout)
    except Exception:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _write_manifest(mode: str, run_id: str, status: str, summary_path: Path, config: IncidentRunConfig, repo_info: dict[str, str], evidence_dir: Path, started_at: float, finished_at: float) -> Path:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    image_id = _optional_stdout(["docker", "image", "inspect", "agent-runtime-os:openeuler", "--format", "{{.Id}}"])
    codex_version = _optional_stdout(["codex", "--version"])
    manifest = {
        "mode": mode,
        "run_id": run_id,
        "status": status,
        "summary": str(summary_path),
        "git_commit": _source_commit(),
        "demo_base_commit": repo_info["base_commit"],
        "docker_image_id": image_id,
        "codex_version": codex_version,
        "deepseek_model": config.deepseek_model,
        "started_at": started_at,
        "finished_at": finished_at,
        "source_repo": repo_info["prepared_repo"],
        "original_source_repo": repo_info["source_repo"],
        "git_status": repo_info["git_status"],
    }
    path = evidence_dir / f"{run_id}.log"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def _run(
    mode: ExecutionMode,
    repo: Path,
    require_real: bool,
    max_concurrency: int,
    max_repair_rounds: int,
    task_timeout_s: int,
    workflow_timeout_s: int,
    evidence_dir: Path,
) -> int:
    if require_real and not (os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY")):
        print("[FAIL] missing DEEPSEEK_API_KEY or LLM_API_KEY")
        return 1
    if require_real and not (os.getenv("OPENAI_API_KEY") or os.getenv("CODEX_API_KEY")):
        print("[FAIL] missing OPENAI_API_KEY or CODEX_API_KEY")
        return 1
    if not require_real and (not (os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY")) or not (os.getenv("OPENAI_API_KEY") or os.getenv("CODEX_API_KEY"))):
        print("[SKIP] real Direct E2E requires DeepSeek and Codex keys")
        return 0
    if not os.getenv("LLM_API_KEY") and os.getenv("DEEPSEEK_API_KEY"):
        os.environ["LLM_API_KEY"] = os.environ["DEEPSEEK_API_KEY"]
    if not os.getenv("CODEX_API_KEY") and os.getenv("OPENAI_API_KEY"):
        os.environ["CODEX_API_KEY"] = os.environ["OPENAI_API_KEY"]

    run_id = f"{mode.value}_real_{uuid4().hex[:12]}"
    repo_info = prepare_e2e_repo(repo, run_id=run_id)
    prepared_repo = Path(repo_info["prepared_repo"])
    _ensure_git_safe_directory(prepared_repo)
    config = IncidentRunConfig(
        execution_mode=mode,
        run_id=run_id,
        thread_id=f"thread_{uuid4().hex[:12]}",
        source_repo=str(prepared_repo),
        base_commit=repo_info["base_commit"],
        max_concurrency=max_concurrency,
        task_timeout_s=task_timeout_s,
        workflow_timeout_s=workflow_timeout_s,
        max_repair_rounds=max_repair_rounds,
        fault_mode=False,
    )
    started_at = time.time()
    result = await IncidentRunService().execute_run(config, "修复认证、JWT和订单安全问题")
    finished_at = time.time()
    summary = result["summary"]
    out_dir = Path("run-data/live") / config.run_id
    (out_dir / "e2e_evidence.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path = _write_manifest(mode.value, config.run_id, str(summary.get("status")), out_dir / "summary.json", config, repo_info, evidence_dir, started_at, finished_at)
    print(json.dumps({"run_id": config.run_id, "mode": mode.value, "status": summary.get("status"), "summary": str(out_dir / "summary.json"), "manifest": str(manifest_path)}, ensure_ascii=False))
    return 0 if summary.get("status") == "SUCCESS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", default=str(DEFAULT_REPO))
    parser.add_argument("--require-real", action="store_true")
    parser.add_argument("--max-concurrency", type=int, default=int(os.getenv("INCIDENT_REAL_MAX_CONCURRENCY", "1")))
    parser.add_argument("--max-repair-rounds", type=int, default=int(os.getenv("INCIDENT_REAL_MAX_REPAIR_ROUNDS", "2")))
    parser.add_argument("--task-timeout-s", type=int, default=int(os.getenv("INCIDENT_REAL_TASK_TIMEOUT_S", "900")))
    parser.add_argument("--workflow-timeout-s", type=int, default=int(os.getenv("INCIDENT_REAL_WORKFLOW_TIMEOUT_S", "3600")))
    parser.add_argument("--evidence-dir", default=str(ROOT / "final-evidence/direct-e2e"))
    args = parser.parse_args()
    return asyncio.run(
        _run(
            ExecutionMode.DIRECT,
            Path(args.source_repo).resolve(),
            args.require_real,
            args.max_concurrency,
            args.max_repair_rounds,
            args.task_timeout_s,
            args.workflow_timeout_s,
            Path(args.evidence_dir),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
