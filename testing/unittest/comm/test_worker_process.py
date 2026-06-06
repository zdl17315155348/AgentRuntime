import asyncio
import os
import subprocess
import sys

import anyio
import pytest

from aruntime.comm.router import MessageRouter
from aruntime.comm.transport import start_uds_server


@pytest.mark.anyio
async def test_agent_worker_process_exec_task_roundtrip(tmp_path):
    sock_path = tmp_path / "agentd.sock"
    router = MessageRouter()
    loop = asyncio.get_running_loop()
    fut = loop.create_future()

    async def on_task_result(agent_name: str, data: dict) -> None:
        if data.get("type") != "task_result":
            return
        if data.get("task_id") != "t1":
            return
        if not fut.done():
            fut.set_result({"agent_name": agent_name, **data})

    server = await start_uds_server(str(sock_path), router, task_result_handler=on_task_result)
    proc = None
    try:
        env = os.environ.copy()
        env["AGENT_NAME"] = "A"
        env["AGENTD_UDS_PATH"] = str(sock_path)
        env["LLM_BACKEND"] = "mock"
        env["LLM_API_KEY"] = ""
        proc = subprocess.Popen(
            [sys.executable, "-m", "aruntime.worker.agent_worker"],
            cwd=os.path.join(os.path.dirname(__file__), "..", "..", ".."),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        ok = await router.wait_connected("A", timeout_s=5.0)
        assert ok is True

        sent = await router.send_event("A", {
            "type": "exec_task",
            "task_id": "t1",
            "system_prompt": "你是一个测试员",
            "user_message": "{'request': 'hi'}",
            "task_input": {"request": "hi"},
        })
        assert sent is True

        with anyio.fail_after(5):
            data = await fut
        assert data["status"] == "SUCCESS"
        assert isinstance(data.get("output"), str)
    finally:
        server.close()
        await server.wait_closed()
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
