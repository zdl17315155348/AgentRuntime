import httpx
import pytest
import os
import time


def wait_task_done(client, task_id: str, timeout_s: float = 15.0) -> dict:
    start = time.time()
    while time.time() - start < timeout_s:
        data = client.get(f"/tasks/{task_id}").json()
        if data["status"] in ("SUCCESS", "FAILED", "TIMEOUT"):
            return data
        time.sleep(0.2)
    raise AssertionError(task_id)


def test_worker_fallback_attempt_and_downstream_continue():
    base_url = os.getenv("AGENTD_BASE_URL", "http://127.0.0.1:8234")
    with httpx.Client(base_url=base_url, timeout=10, trust_env=False) as client:
        client.get("/metrics")
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
        assert data["status"] == "TIMEOUT"
        assert len(data["attempts"]) >= 1
        assert data["definition"]["agent_name"] == coder_a
        assert any(attempt["agent_name"] == coder_a for attempt in data["attempts"])
        down = wait_task_done(client, downstream["task_id"])
        assert down["status"] == "SUCCESS"
        metrics = client.get("/metrics").json()
        assert metrics["resource"]["leases"] == []
