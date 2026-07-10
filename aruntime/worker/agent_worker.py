import asyncio
import json
import os
import sys
from uuid import uuid4

from aruntime.llm.gateway import LLMGateway


def _encode_line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def _decode_line(line: bytes) -> dict:
    return json.loads(line.decode("utf-8").strip())


async def _run() -> None:
    agent_name = os.getenv("AGENT_NAME", "").strip()
    uds_path = os.getenv("AGENTD_UDS_PATH", "/tmp/agent-runtime-agentd.sock").strip()
    auth_token = os.getenv("AGENT_AUTH_TOKEN", "")
    if not agent_name:
        raise RuntimeError("AGENT_NAME is required")

    llm_backend = os.getenv("LLM_BACKEND", "mock")
    llm_api_key = os.getenv("LLM_API_KEY", "")
    llm_gateway = LLMGateway(backend=llm_backend, api_key=llm_api_key)

    reader, writer = await asyncio.open_unix_connection(uds_path)
    writer.write(_encode_line({"type": "register", "agent_name": agent_name, "token": auth_token}))
    await writer.drain()

    async def heartbeat_loop() -> None:
        while True:
            await asyncio.sleep(1.0)
            writer.write(_encode_line({"type": "heartbeat", "agent_name": agent_name}))
            await writer.drain()

    heartbeat_task = asyncio.create_task(heartbeat_loop())

    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            data = _decode_line(line)
            if data.get("type") != "exec_task":
                continue

            task_id = str(data.get("task_id") or "").strip()
            if not task_id:
                continue
            system_prompt = str(data.get("system_prompt") or "")
            user_message = str(data.get("user_message") or "")
            task_input = data.get("task_input")
            logical_context_reuse_hit = False
            if isinstance(task_input, dict):
                runtime_context = task_input.get("runtime_context", {})
                if isinstance(runtime_context, dict):
                    execution = runtime_context.get("execution", {})
                    if isinstance(execution, dict):
                        logical_context_reuse_hit = bool(
                            execution.get("logical_context_reuse_hit")
                            or execution.get("prefix_cache_hit")
                            or execution.get("cache_hit")
                        )

            status = "SUCCESS"
            output = ""
            error = ""
            usage = {}
            try:
                if llm_gateway.backend == "mock" and isinstance(task_input, dict):
                    test_cfg = task_input.get("__test", {})
                    if isinstance(test_cfg, dict):
                        sleep_ms = test_cfg.get("sleep_ms")
                        if isinstance(sleep_ms, (int, float)) and sleep_ms > 0:
                            await asyncio.sleep(float(sleep_ms) / 1000.0)
                        if test_cfg.get("crash_worker") is True:
                            os._exit(2)
                        if test_cfg.get("force_error") is True:
                            raise RuntimeError("forced error")

                llm_result = llm_gateway.chat_with_stats(
                    system_prompt,
                    user_message,
                    prefix_cache_hit=logical_context_reuse_hit,
                )
                output = llm_result.output
                usage = llm_result.to_dict()
            except Exception as e:
                status = "FAILED"
                error = str(e)

            result_msg = {
                "type": "task_result",
                "message_id": f"result_{uuid4().hex}",
                "task_id": task_id,
                "status": status,
                "output": output,
                "error": error,
                "usage": usage,
            }

            for _ in range(3):
                writer.write(_encode_line(result_msg))
                await writer.drain()
                try:
                    ack = await asyncio.wait_for(reader.readline(), timeout=2.0)
                except Exception:
                    continue
                if not ack:
                    continue
                try:
                    ack_data = _decode_line(ack)
                except Exception:
                    continue
                if ack_data.get("type") == "ack" and ack_data.get("task_id") == task_id:
                    break
    finally:
        heartbeat_task.cancel()
        writer.close()
        await writer.wait_closed()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
