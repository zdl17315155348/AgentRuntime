import asyncio
import json
import os
import sys

from aruntime.llm.gateway import LLMGateway


def _encode_line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def _decode_line(line: bytes) -> dict:
    return json.loads(line.decode("utf-8").strip())


async def _run() -> None:
    agent_name = os.getenv("AGENT_NAME", "").strip()
    uds_path = os.getenv("AGENTD_UDS_PATH", "/tmp/agent-runtime-agentd.sock").strip()
    if not agent_name:
        raise RuntimeError("AGENT_NAME is required")

    llm_backend = os.getenv("LLM_BACKEND", "mock")
    llm_api_key = os.getenv("LLM_API_KEY", "")
    llm_gateway = LLMGateway(backend=llm_backend, api_key=llm_api_key)

    reader, writer = await asyncio.open_unix_connection(uds_path)
    writer.write(_encode_line({"type": "register", "agent_name": agent_name}))
    await writer.drain()

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

            status = "SUCCESS"
            output = ""
            error = ""
            try:
                if llm_gateway.backend == "mock" and isinstance(task_input, dict):
                    test_cfg = task_input.get("__test", {})
                    if isinstance(test_cfg, dict):
                        sleep_ms = test_cfg.get("sleep_ms")
                        if isinstance(sleep_ms, (int, float)) and sleep_ms > 0:
                            await asyncio.sleep(float(sleep_ms) / 1000.0)
                        if test_cfg.get("force_error") is True:
                            raise RuntimeError("forced error")

                output = llm_gateway.chat(system_prompt, user_message)
            except Exception as e:
                status = "FAILED"
                error = str(e)

            writer.write(_encode_line({
                "type": "task_result",
                "task_id": task_id,
                "status": status,
                "output": output,
                "error": error,
            }))
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)

