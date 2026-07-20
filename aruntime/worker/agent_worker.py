import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from aruntime.backends.codex_cli import CodexCLIBackend
from aruntime.backends.direct_tool import DirectToolBackend
from aruntime.backends.legacy_llm import LegacyLLMBackend
from aruntime.backends.native_planner import NativePlannerBackend
from aruntime.backends.registry import BackendRegistry
from aruntime.backends.base import BackendExecutionRequest
from aruntime.core.models import AgentBackendConfig, AgentBackendType, AgentSpec, WorkspaceSpec
from aruntime.executor.task_executor import TaskExecutor
from aruntime.llm.gateway import LLMGateway
from aruntime.tools.file_tools import ReadFileTool, SearchCodeTool, WriteFileTool
from aruntime.tools.git_tools import GitDiffTool, GitStatusTool
from aruntime.tools.pytest_tool import RunPytestTool
from aruntime.tools.repo_scan_tool import RepoScanTool
from aruntime.tools.registry import ToolRegistry
from aruntime.tools.shell_tool import RunCommandTool


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
    agent_spec: AgentSpec,
    backend_registry: BackendRegistry,
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
    artifacts = []
    exit_code = None
    backend_type = ""
    runtime_context = {}
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

        workspace_data = data.get("workspace") if isinstance(data.get("workspace"), dict) else {}
        if workspace_data:
            workspace = WorkspaceSpec(**workspace_data)
        else:
            workspace_root = Path(os.getenv("AGENT_WORKSPACE", os.getcwd())).resolve()
            workspace = WorkspaceSpec(source_repo=str(workspace_root), workspace_path=str(workspace_root))

        backend_config = agent_spec.backend
        tool_request = task_input.get("__tool") if isinstance(task_input, dict) else None
        if backend_config.type == AgentBackendType.LEGACY_LLM and isinstance(tool_request, dict) and tool_request.get("name"):
            backend_config = AgentBackendConfig(type=AgentBackendType.DIRECT_TOOL, timeout_s=backend_config.timeout_s)

        request = BackendExecutionRequest(
            task_id=task_id,
            attempt_id=attempt_id,
            agent_name=agent_spec.agent_name,
            system_prompt=system_prompt,
            user_message=user_message,
            task_input=task_input if isinstance(task_input, dict) else {},
            workspace=workspace,
            runtime_context=runtime_context if isinstance(runtime_context, dict) else {},
            timeout_s=int(data.get("timeout_s") or backend_config.timeout_s or 300),
            token_budget=data.get("token_budget"),
        )
        backend = backend_registry.create(
            backend_config,
            {"llm_gateway": llm_gateway, "executor": executor, "agent_spec": agent_spec},
        )

        async def emit_event(event: dict) -> None:
            await send_json(
                {
                    "type": "backend_event",
                    "task_id": request.task_id,
                    "attempt_id": request.attempt_id,
                    "event": event,
                }
            )
            if event.get("name") == "backend.started":
                await send_json(
                    {
                        "type": "backend_started",
                        "task_id": request.task_id,
                        "attempt_id": request.attempt_id,
                        "backend_type": event.get("backend_type") or backend_config.type.value,
                        "backend_pid": event.get("backend_pid"),
                        "backend_session_id": event.get("backend_session_id"),
                    }
                )

        await backend.prepare(request)
        backend_result = await backend.execute(request, emit_event)
        await backend.cleanup(request)
        status = backend_result.status
        output = backend_result.output
        error = backend_result.error
        usage = backend_result.usage
        artifacts = [artifact.model_dump(mode="json") for artifact in backend_result.artifacts]
        exit_code = backend_result.exit_code
        backend_type = backend_result.backend_type
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
            "backend_type": backend_type,
            "exit_code": exit_code,
            "artifacts": artifacts,
        },
    )


async def _run() -> None:
    agent_name = os.getenv("AGENT_NAME", "").strip()
    uds_path = os.getenv("AGENTD_UDS_PATH", "/tmp/agent-runtime-agentd.sock").strip()
    auth_token = os.getenv("AGENT_AUTH_TOKEN", "")
    if not agent_name:
        raise RuntimeError("AGENT_NAME is required")

    spec_json = os.getenv("AGENT_SPEC_JSON", "")
    if spec_json:
        agent_spec = AgentSpec(**json.loads(spec_json))
    else:
        agent_spec = AgentSpec(agent_name=agent_name, role=agent_name)
    llm_gateway = LLMGateway(backend=os.getenv("LLM_BACKEND", "mock"), api_key=os.getenv("LLM_API_KEY", ""))
    registry = ToolRegistry()
    for tool in (RepoScanTool(), ReadFileTool(), SearchCodeTool(), WriteFileTool(), GitDiffTool(), GitStatusTool(), RunPytestTool(), RunCommandTool()):
        registry.register(tool)
    executor = TaskExecutor(registry)
    backend_registry = BackendRegistry()
    backend_registry.register(AgentBackendType.LEGACY_LLM, lambda config, deps: LegacyLLMBackend(config, deps))
    backend_registry.register(AgentBackendType.DIRECT_TOOL, lambda config, deps: DirectToolBackend(config, deps))
    backend_registry.register(AgentBackendType.CODEX_CLI, lambda config, deps: CodexCLIBackend(config, deps))
    backend_registry.register(AgentBackendType.NATIVE_PLANNER, lambda config, deps: NativePlannerBackend(config, deps))

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
                task = asyncio.create_task(_run_exec_task(data, send_json, llm_gateway, executor, agent_spec, backend_registry))
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
