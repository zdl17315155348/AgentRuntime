import os
import subprocess
import sys
import time

import httpx
import pytest


def _wait_until_ready(base_url: str, timeout_s: float = 15.0) -> None:
    start = time.time()
    last_exc: Exception | None = None
    while time.time() - start < timeout_s:
        try:
            with httpx.Client(base_url=base_url, timeout=2) as client:
                resp = client.get("/metrics")
                if resp.status_code == 200:
                    return
        except Exception as e:
            last_exc = e
        time.sleep(0.2)
    raise RuntimeError(f"agentd 未在 {timeout_s}s 内就绪: {last_exc}")


def test_smoke_real_llm_end_to_end():
    backend = os.getenv("SMOKE_LLM_BACKEND", os.getenv("LLM_BACKEND", "deepseek")).strip()
    api_key = os.getenv("SMOKE_LLM_API_KEY", os.getenv("LLM_API_KEY", "")).strip()

    if not api_key or backend == "mock":
        pytest.skip("需要真实 LLM：请设置 SMOKE_LLM_API_KEY（或 LLM_API_KEY），并确保 LLM_BACKEND != mock")

    base_url = "http://127.0.0.1:8234"

    env = os.environ.copy()
    env["LLM_BACKEND"] = backend
    env["LLM_API_KEY"] = api_key
    env.setdefault("SCHEDULER_TYPE", "fifo")

    proc: subprocess.Popen | None = None
    try:
        _wait_until_ready(base_url, timeout_s=1.0)
    except Exception:
        proc = subprocess.Popen(
            [sys.executable, "-m", "aruntime.daemon.main"],
            cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    try:
        _wait_until_ready(base_url, timeout_s=20.0)

        with httpx.Client(base_url=base_url, timeout=30) as client:
            resp = client.post(
                "/agents",
                json={
                    "agent_name": f"smoke_real_llm_{int(time.time())}",
                    "role": "冒烟测试员",
                    "system_prompt": "你是一个冒烟测试助手，请简短回答。",
                },
            )
            assert resp.status_code == 200, resp.text
            agent_name = resp.json()["agent_name"]

            resp = client.post(
                "/tasks",
                json={
                    "agent_name": agent_name,
                    "task_input": {"request": "请返回字符串 OK（只返回 OK）。"},
                },
            )
            assert resp.status_code == 200, resp.text
            task_id = resp.json()["task_id"]

            result = None
            for _ in range(40):
                time.sleep(0.5)
                resp = client.get(f"/tasks/{task_id}")
                assert resp.status_code == 200, resp.text
                data = resp.json()
                if data["status"] in ("SUCCESS", "FAILED"):
                    result = data
                    break

            assert result is not None, "任务未在预期时间内完成"
            assert result["status"] == "SUCCESS", result
            assert result.get("result"), result

            output = (result["result"].get("output") or "").strip()
            assert output, result
            assert not output.startswith("[Mock]"), "检测到 mock 输出，说明没有走真实 LLM"

    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
