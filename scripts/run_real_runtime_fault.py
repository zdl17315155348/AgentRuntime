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
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from aruntime.api.client import AgentRuntimeClient
from applications.incident_repair.config import ExecutionMode, IncidentRunConfig
from applications.incident_repair.services.run_service import IncidentRunService, register_demo_agents
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


def _optional_stdout(args: list[str], cwd: Path = ROOT, timeout: int = 10) -> str:
    try:
        proc = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=False, timeout=timeout)
    except Exception:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _source_commit() -> str:
    return _optional_stdout(["git", "-c", f"safe.directory={ROOT}", "rev-parse", "HEAD"]) or "HEAD"


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


def _agentd_runtime_config(base_url: str) -> dict:
    try:
        data = httpx.get(f"{base_url}/metrics", timeout=3, trust_env=False).json()
    except Exception:
        return {}
    config = data.get("runtime_config")
    return config if isinstance(config, dict) else {}


def _run_events(base_url: str, run_id: str, after_id: int = 0) -> list[dict]:
    try:
        data = httpx.get(f"{base_url}/runs/{run_id}/events", params={"after_id": after_id}, timeout=3, trust_env=False).json()
    except Exception:
        return []
    events = data.get("events")
    return events if isinstance(events, list) else []


def _run_summary(base_url: str, run_id: str) -> dict:
    try:
        data = httpx.get(f"{base_url}/runs/{run_id}/summary", timeout=5, trust_env=False).json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _task(base_url: str, task_id: str) -> dict:
    try:
        data = httpx.get(f"{base_url}/tasks/{task_id}", timeout=3, trust_env=False).json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _event_name(event: dict) -> str:
    return str(event.get("name") or "")


def _event_detail(event: dict) -> dict:
    raw = event.get("data")
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
    elif isinstance(raw, dict):
        payload = raw
    else:
        payload = {}
    detail = event.get("detail")
    if isinstance(detail, dict):
        payload.update(detail)
    return payload


def _event_agent_name(base_url: str, event: dict) -> str:
    detail = _event_detail(event)
    if detail.get("agent_name"):
        return str(detail["agent_name"])
    task_id = str(event.get("task_id") or detail.get("task_id") or "")
    attempt_id = str(detail.get("attempt_id") or "")
    if not task_id:
        return ""
    task = _task(base_url, task_id)
    for attempt in task.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        if attempt_id and attempt.get("attempt_id") != attempt_id:
            continue
        if attempt.get("agent_name"):
            return str(attempt["agent_name"])
    return ""


async def _wait_and_inject(base_url: str, run_id: str, timeout_s: int) -> dict:
    client = AgentRuntimeClient(base_url)
    deadline = time.time() + timeout_s
    last_id = 0
    seen: list[dict] = []
    injected: dict | None = None
    while time.time() < deadline:
        events = _run_events(base_url, run_id, last_id)
        for event in events:
            try:
                last_id = max(last_id, int(event.get("id") or event.get("event_id") or last_id))
            except (TypeError, ValueError):
                pass
            seen.append(event)
            name = _event_name(event)
            if injected is None and name in {"backend_started", "backend.started"} and _event_agent_name(base_url, event) == "coder_a":
                injected = client.inject_worker_sigkill("coder_a")
        summary = _run_summary(base_url, run_id)
        if summary.get("status") in {"SUCCESS", "FAILED", "TIMEOUT", "CANCELLED"}:
            break
        await asyncio.sleep(0.25)
    return {"injection": injected or {"injected": False, "reason": "coder_a backend_started not observed"}, "events": seen}


def _fault_evidence(events: list[dict], runtime_summary: dict) -> dict:
    names = [_event_name(event) for event in events]
    attempts = runtime_summary.get("attempts") if isinstance(runtime_summary.get("attempts"), list) else []
    coder_attempts = [attempt for attempt in attempts if attempt.get("agent_name") in {"coder_a", "coder_b"}]
    worker_pids = [attempt.get("worker_pid") for attempt in coder_attempts if attempt.get("worker_pid")]
    backend_pids = [attempt.get("backend_pid") for attempt in coder_attempts if attempt.get("backend_pid")]
    worktrees = [attempt.get("workspace_path") for attempt in coder_attempts if attempt.get("workspace_path")]
    task_ids = {attempt.get("task_id") for attempt in coder_attempts if attempt.get("task_id")}
    fallback_agents = {attempt.get("agent_name") for attempt in coder_attempts}
    return {
        "backend_started": names.count("backend_started") + names.count("backend.started"),
        "worker_lost": names.count("worker.lost"),
        "resource_lease_reclaimed": names.count("lease.reclaim") + int((runtime_summary.get("faults") or {}).get("leases_reclaimed") or 0),
        "attempt_failed": len([attempt for attempt in coder_attempts if attempt.get("status") in {"FAILED", "TIMEOUT"}]),
        "fallback_created": names.count("task.fallback"),
        "attempt_success": len([attempt for attempt in coder_attempts if attempt.get("status") == "SUCCESS"]),
        "same_task_id": len(task_ids) == 1 and len(coder_attempts) >= 2,
        "attempt_id_changed": len({attempt.get("attempt_id") for attempt in coder_attempts if attempt.get("attempt_id")}) >= 2,
        "worker_pid_changed": len(set(worker_pids)) >= 2,
        "codex_pid_changed": len(set(backend_pids)) >= 2,
        "agent_switched_to_coder_b": "coder_b" in fallback_agents,
        "new_worktree": len(set(worktrees)) >= 2,
        "recovery_context_loaded": any(attempt.get("recovery_context_id") for attempt in coder_attempts),
        "leases_active": len((runtime_summary.get("resource") or {}).get("leases") or []),
    }


def _write_manifest(
    run_id: str,
    status: str,
    app_summary_path: Path,
    repo_info: dict[str, str],
    evidence_dir: Path,
    started_at: float,
    finished_at: float,
    injection: dict,
    runtime_summary: dict,
    fault_evidence: dict,
) -> Path:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "mode": "fault",
        "run_id": run_id,
        "status": status,
        "summary": str(app_summary_path),
        "runtime_summary": runtime_summary,
        "fault_evidence": fault_evidence,
        "injection": injection,
        "git_commit": _source_commit(),
        "demo_base_commit": repo_info["base_commit"],
        "docker_image_id": _optional_stdout(["docker", "image", "inspect", "agent-runtime-os:openeuler", "--format", "{{.Id}}"]),
        "codex_version": _optional_stdout(["codex", "--version"]),
        "deepseek_model": "deepseek-chat",
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
    repo: Path,
    require_real: bool,
    base_url: str,
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
        print("[SKIP] real Runtime Fault E2E requires DeepSeek and Codex keys")
        return 0
    if not os.getenv("LLM_API_KEY") and os.getenv("DEEPSEEK_API_KEY"):
        os.environ["LLM_API_KEY"] = os.environ["DEEPSEEK_API_KEY"]
    if not os.getenv("CODEX_API_KEY") and os.getenv("OPENAI_API_KEY"):
        os.environ["CODEX_API_KEY"] = os.environ["OPENAI_API_KEY"]
    if not _wait_agentd(base_url):
        print(f"[FAIL] agentd not ready at {base_url}")
        return 1
    runtime_config = _agentd_runtime_config(base_url)
    if require_real:
        if str(runtime_config.get("llm_backend") or "").strip() == "mock":
            print("[FAIL] agentd is using mock LLM backend")
            return 1
        if runtime_config and not runtime_config.get("llm_api_key_present"):
            print("[FAIL] agentd has no LLM API key")
            return 1

    run_id = f"fault_real_{uuid4().hex[:12]}"
    repo_info = prepare_e2e_repo(repo, run_id=run_id)
    prepared_repo = Path(repo_info["prepared_repo"])
    _ensure_git_safe_directory(prepared_repo)
    client = AgentRuntimeClient(base_url)
    register_demo_agents(client)
    config = IncidentRunConfig(
        execution_mode=ExecutionMode.RUNTIME,
        run_id=run_id,
        thread_id=f"thread_{uuid4().hex[:12]}",
        source_repo=str(prepared_repo),
        base_commit=repo_info["base_commit"],
        max_concurrency=max_concurrency,
        task_timeout_s=task_timeout_s,
        workflow_timeout_s=workflow_timeout_s,
        max_repair_rounds=max_repair_rounds,
        fault_mode=True,
    )
    service = IncidentRunService()
    started_at = time.time()
    workflow = asyncio.create_task(service.execute_run(config, "修复认证、JWT和订单安全问题", {"client": client}))
    fault = asyncio.create_task(_wait_and_inject(base_url, run_id, task_timeout_s))
    result = await asyncio.wait_for(workflow, timeout=workflow_timeout_s + 60)
    fault_result = await fault
    finished_at = time.time()
    summary = result["summary"]
    out_dir = Path("run-data/live") / config.run_id
    app_summary_path = out_dir / "summary.json"
    runtime_summary = _run_summary(base_url, run_id)
    fault_evidence = _fault_evidence(fault_result["events"], runtime_summary)
    (out_dir / "fault_evidence.json").write_text(json.dumps(fault_evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path = _write_manifest(
        config.run_id,
        str(summary.get("status")),
        app_summary_path,
        repo_info,
        evidence_dir,
        started_at,
        finished_at,
        fault_result["injection"],
        runtime_summary,
        fault_evidence,
    )
    print(json.dumps({"run_id": config.run_id, "mode": "fault", "status": summary.get("status"), "summary": str(app_summary_path), "manifest": str(manifest_path)}, ensure_ascii=False))
    required = (
        summary.get("status") == "SUCCESS"
        and fault_evidence["worker_lost"] >= 1
        and fault_evidence["fallback_created"] >= 1
        and fault_evidence["agent_switched_to_coder_b"]
        and fault_evidence["leases_active"] == 0
    )
    return 0 if required else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", default=str(DEFAULT_REPO))
    parser.add_argument("--base-url", default=os.getenv("AGENTD_BASE_URL", "http://127.0.0.1:8234"))
    parser.add_argument("--require-real", action="store_true")
    parser.add_argument("--max-concurrency", type=int, default=int(os.getenv("INCIDENT_REAL_MAX_CONCURRENCY", "1")))
    parser.add_argument("--max-repair-rounds", type=int, default=int(os.getenv("INCIDENT_REAL_MAX_REPAIR_ROUNDS", "2")))
    parser.add_argument("--task-timeout-s", type=int, default=int(os.getenv("INCIDENT_REAL_TASK_TIMEOUT_S", "900")))
    parser.add_argument("--workflow-timeout-s", type=int, default=int(os.getenv("INCIDENT_REAL_WORKFLOW_TIMEOUT_S", "3600")))
    parser.add_argument("--evidence-dir", default=str(ROOT / "final-evidence/fault-e2e"))
    args = parser.parse_args()
    return asyncio.run(
        _run(
            Path(args.source_repo).resolve(),
            args.require_real,
            args.base_url,
            args.max_concurrency,
            args.max_repair_rounds,
            args.task_timeout_s,
            args.workflow_timeout_s,
            Path(args.evidence_dir),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
