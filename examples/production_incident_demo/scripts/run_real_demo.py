from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "target_repo"
TEMPLATE = ROOT / "target_repo_template"
OUTPUT = ROOT / "output" / "real"
BASE_URL = os.getenv("AGENTD_BASE_URL", "http://127.0.0.1:8234")


def reset_repo() -> None:
    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(TEMPLATE, TARGET)
    subprocess.run(["git", "init"], cwd=TARGET, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "AgentRuntime Demo"], cwd=TARGET, check=True)
    subprocess.run(["git", "config", "user.email", "demo@agentruntime.local"], cwd=TARGET, check=True)
    subprocess.run(["git", "add", "."], cwd=TARGET, check=True)
    subprocess.run(["git", "commit", "-m", "demo baseline"], cwd=TARGET, check=True, capture_output=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)


def wait_agentd(client: httpx.Client) -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if client.get("/metrics").status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError("agentd not ready")


def wait_run(client: httpx.Client, root_task_id: str, timeout_s: float) -> dict:
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        last = client.get(f"/runs/{root_task_id}/summary").json()
        tasks = last.get("tasks", {})
        terminal = tasks.get("running", 0) == 0 and tasks.get("ready", 0) == 0
        if terminal and tasks.get("failed", 0) > 0:
            raise RuntimeError(f"run failed: {json.dumps(last, ensure_ascii=False)[:2000]}")
        if tasks.get("running", 0) == 0 and tasks.get("ready", 0) == 0 and tasks.get("failed", 0) == 0 and tasks.get("success", 0) >= 3:
            return last
        time.sleep(2)
    raise RuntimeError(f"run timed out: {json.dumps(last, ensure_ascii=False)[:2000]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-s", type=float, default=900)
    parser.add_argument("--inject-fault", action="store_true")
    args = parser.parse_args()
    reset_repo()
    with httpx.Client(base_url=BASE_URL, timeout=30, trust_env=False) as client:
        wait_agentd(client)
    subprocess.run(["python3", str(ROOT / "scripts" / "register_agents.py")], check=True)
    with httpx.Client(base_url=BASE_URL, timeout=30, trust_env=False) as client:
        response = client.post(
            "/tasks",
            json={
                "agent_name": "architect",
                "context_id": "incident-demo-real",
                "task_input": {
                    "request": "修复登录、JWT、订单越权和幂等问题，保持测试通过。",
                    "workflow_mode": "planner",
                },
                "required_backend": "native_planner",
                "workspace": {"source_repo": str(TARGET), "base_ref": "HEAD", "read_only": True},
                "timeout_ms": 600000,
            },
        )
        response.raise_for_status()
        root_task_id = response.json()["task_id"]
        if args.inject_fault:
            time.sleep(5)
            client.post("/debug/faults/workers/coder_a/sigkill")
        summary = wait_run(client, root_task_id, args.timeout_s)
        events = client.get(f"/runs/{root_task_id}/events").json()
    (OUTPUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT / "events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"root_task_id": root_task_id, "output": str(OUTPUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
