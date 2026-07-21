import httpx
import pytest
import os
import subprocess
import sys
import time


def wait_task_done(client, task_id: str, timeout_s: float = 15.0) -> dict:
    start = time.time()
    while time.time() - start < timeout_s:
        data = client.get(f"/tasks/{task_id}").json()
        if data["status"] in ("SUCCESS", "FAILED", "CANCELLED"):
            return data
        time.sleep(0.2)
    raise AssertionError(task_id)


def wait_agentd_ready(client, timeout_s: float = 10.0) -> None:
    start = time.time()
    last_error = None
    while time.time() - start < timeout_s:
        try:
            response = client.get("/metrics")
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.2)
    raise AssertionError(f"agentd not ready: {last_error}")


def start_agentd_if_needed(base_url: str) -> subprocess.Popen | None:
    with httpx.Client(base_url=base_url, timeout=1, trust_env=False) as client:
        try:
            wait_agentd_ready(client, timeout_s=1.0)
            return None
        except AssertionError:
            pass

    env = os.environ.copy()
    env.update(
        {
            "LLM_BACKEND": "mock",
            "LLM_API_KEY": "",
            "SCHEDULER_TYPE": "dag",
            "AGENTD_STATE_DB": f"/tmp/agent-runtime-worker-fallback-{os.getpid()}.db",
            "AGENTD_UDS_PATH": f"/tmp/agent-runtime-worker-fallback-{os.getpid()}.sock",
        }
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "aruntime.daemon.main"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    with httpx.Client(base_url=base_url, timeout=10, trust_env=False) as client:
        try:
            wait_agentd_ready(client, timeout_s=10.0)
        except Exception:
            proc.terminate()
            proc.wait(timeout=5)
            raise
    return proc


def test_worker_fallback_attempt_and_downstream_continue():
    base_url = os.getenv("AGENTD_BASE_URL", "http://127.0.0.1:8234")
    proc = start_agentd_if_needed(base_url)
    try:
        with httpx.Client(base_url=base_url, timeout=10, trust_env=False) as client:
            wait_agentd_ready(client)
            suffix = str(int(time.time() * 1000))
            coder_a = f"int_coder_a_{suffix}"
            coder_b = f"int_coder_b_{suffix}"
            tester = f"int_tester_{suffix}"
            client.post("/agents", json={"agent_name": coder_a, "role": "coder"})
            client.post("/agents", json={"agent_name": coder_b, "role": "coder"})
            client.post("/agents", json={"agent_name": tester, "role": "tester"})
            task = client.post("/tasks", json={
                "agent_name": coder_a,
                "task_input": {"request": "fallback", "__test": {"crash_worker": True}},
                "failure_policy": {"mode": "fallback", "fallback_agent": coder_b, "max_retries": 0, "timeout_ms": 1000},
                "resource_request": {"llm_max_concurrent": 1},
            }).json()
            downstream = client.post("/tasks", json={
                "agent_name": tester,
                "task_input": {"request": "test"},
                "dependencies": [task["task_id"]],
                "on_failure": {task["task_id"]: "fail_open"},
            }).json()

            data = wait_task_done(client, task["task_id"])
            assert data["status"] == "SUCCESS"
            assert len(data["attempts"]) >= 2
            assert data["definition"]["agent_name"] == coder_a
            assert any(attempt["agent_name"] == coder_a and attempt["status"] in ("FAILED", "TIMEOUT") for attempt in data["attempts"])
            assert any(attempt["agent_name"] == coder_b and attempt["status"] == "SUCCESS" for attempt in data["attempts"])
            down = wait_task_done(client, downstream["task_id"])
            assert down["status"] == "SUCCESS"
            metrics = client.get("/metrics").json()
            assert metrics["resource"]["leases"] == []
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=5)
