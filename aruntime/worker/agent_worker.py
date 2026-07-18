import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from aruntime.executor.task_executor import TaskExecutor
from aruntime.llm.gateway import LLMGateway
from aruntime.tools.file_tools import ReadFileTool, SearchCodeTool, WriteFileTool
from aruntime.tools.git_tools import GitDiffTool, GitStatusTool
from aruntime.tools.pytest_tool import RunPytestTool
from aruntime.tools.repo_scan_tool import RepoScanTool
from aruntime.tools.registry import ToolRegistry
from aruntime.tools.shell_tool import RunCommandTool
from aruntime.tools.base import ToolExecutionContext


def _encode_line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def _decode_line(line: bytes) -> dict:
    return json.loads(line.decode("utf-8").strip())


async def _send_result(send_json, result_msg: dict) -> None:
    await send_json(result_msg)


async def _run_exec_task(
    data: dict,
    send_json,
    llm_gateway: LLMGateway,
    executor: TaskExecutor,
    tool_context: ToolExecutionContext,
) -> None:
    task_id = str(data.get("task_id") or "").strip()
    attempt_id = str(data.get("attempt_id") or "").strip()
    if not task_id or not attempt_id:
        return
    system_prompt = str(data.get("system_prompt") or "")
    user_message = str(data.get("user_message") or "")
    task_input = data.get("task_input")
    status = "SUCCESS"
    output = ""
    error = ""
    usage = {}
    try:
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

        tool_request = task_input.get("__tool") if isinstance(task_input, dict) else None
        if isinstance(tool_request, dict) and tool_request.get("name"):
            tool_result = await executor.execute_tool(str(tool_request["name"]), dict(tool_request.get("arguments") or {}), tool_context)
            output = json.dumps(tool_result.output, ensure_ascii=False)
            usage = {"tool": tool_request["name"], "metadata": tool_result.metadata}
            if not tool_result.ok:
                status = "FAILED"
                error = tool_result.error or "tool error"
        else:
            llm_result = llm_gateway.chat_with_stats(
                system_prompt,
                user_message,
                prefix_cache_hit=logical_context_reuse_hit,
            )
            output = llm_result.output
            usage = llm_result.to_dict()
    except asyncio.CancelledError:
        await send_json(
            {
                "type": "task_cancelled",
                "task_id": task_id,
                "attempt_id": attempt_id,
            }
        )
        raise
    except Exception as exc:
        status = "FAILED"
        error = str(exc)

    await _send_result(
        send_json,
        {
            "type": "task_result",
            "message_id": f"result_{uuid4().hex}",
            "task_id": task_id,
            "attempt_id": attempt_id,
            "status": status,
            "output": output,
            "error": error,
            "usage": usage,
        },
    )


async def _run() -> None:
    agent_name = os.getenv("AGENT_NAME", "").strip()
    uds_path = os.getenv("AGENTD_UDS_PATH", "/tmp/agent-runtime-agentd.sock").strip()
    auth_token = os.getenv("AGENT_AUTH_TOKEN", "")
    if not agent_name:
        raise RuntimeError("AGENT_NAME is required")

    llm_gateway = LLMGateway(backend=os.getenv("LLM_BACKEND", "mock"), api_key=os.getenv("LLM_API_KEY", ""))
    registry = ToolRegistry()
    for tool in (RepoScanTool(), ReadFileTool(), SearchCodeTool(), WriteFileTool(), GitDiffTool(), GitStatusTool(), RunPytestTool(), RunCommandTool()):
        registry.register(tool)
    executor = TaskExecutor(registry)
    workspace_root = Path(os.getenv("AGENT_WORKSPACE", os.getcwd())).resolve()
    tool_context = ToolExecutionContext(
        workspace_root=workspace_root,
        allowed_roots=[workspace_root],
        allowed_shell_commands=set(filter(None, os.getenv("AGENTD_SHELL_ALLOWLIST", "").split(","))),
        timeout_s=float(os.getenv("AGENTD_TOOL_TIMEOUT_S", "30")),
        max_output_bytes=int(os.getenv("AGENTD_TOOL_MAX_OUTPUT", "65536")),
    )

    reader, writer = await asyncio.open_unix_connection(uds_path)
    writer.write(_encode_line({"type": "register", "agent_name": agent_name, "token": auth_token}))
    await writer.drain()

    writer_lock = asyncio.Lock()

    async def send_json(payload: dict) -> None:
        async with writer_lock:
            writer.write(_encode_line(payload))
            await writer.drain()

    running: dict[tuple[str, str], asyncio.Task] = {}
    processed_messages: set[str] = set()
    context_updates: list[dict] = []

    async def heartbeat_loop() -> None:
        while True:
            await asyncio.sleep(1.0)
            await send_json({"type": "heartbeat", "agent_name": agent_name})

    heartbeat_task = asyncio.create_task(heartbeat_loop())
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            data = _decode_line(line)
            msg_type = data.get("type")

            if msg_type == "exec_task":
                task_id = str(data.get("task_id") or "").strip()
                attempt_id = str(data.get("attempt_id") or "").strip()
                if not task_id or not attempt_id:
                    await send_json(
                        {
                            "type": "protocol_error",
                            "task_id": task_id,
                            "attempt_id": attempt_id,
                            "error": "task_id and attempt_id are required",
                        }
                    )
                    continue
                key = (task_id, attempt_id)
                if key in running:
                    await send_json(
                        {
                            "type": "protocol_error",
                            "task_id": task_id,
                            "attempt_id": attempt_id,
                            "error": "attempt already running",
                        }
                    )
                    continue
                task = asyncio.create_task(_run_exec_task(data, send_json, llm_gateway, executor, tool_context))
                running[key] = task

                def cleanup(done_task: asyncio.Task, task_key=key) -> None:
                    if running.get(task_key) is done_task:
                        running.pop(task_key, None)

                task.add_done_callback(cleanup)
                continue

            if msg_type == "cancel_task":
                task_id = str(data.get("task_id") or "").strip()
                attempt_id = str(data.get("attempt_id") or "").strip()
                key = (task_id, attempt_id)
                task = running.get(key)
                if task is not None:
                    task.cancel()
                await send_json(
                    {
                        "type": "cancel_ack",
                        "task_id": task_id,
                        "attempt_id": attempt_id,
                        "cancelled": task is not None,
                        **({} if task is not None else {"reason": "attempt_not_running"}),
                    }
                )
                continue

            if msg_type == "agent_message" or (msg_type == "message" and data.get("payload")):
                message_id = str(data.get("message_id") or "")
                if message_id and message_id not in processed_messages:
                    processed_messages.add(message_id)
                await send_json({"type": "agent_message_ack", "message_id": message_id, "agent_name": agent_name})
                continue

            if msg_type == "context_update":
                context_updates.append(dict(data.get("payload") or {}))
                await send_json({"type": "context_update_ack", "message_id": data.get("message_id", ""), "agent_name": agent_name})
                continue
    finally:
        heartbeat_task.cancel()
        for task in running.values():
            task.cancel()
        writer.close()
        await writer.wait_closed()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
