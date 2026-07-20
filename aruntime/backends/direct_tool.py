from __future__ import annotations

import json
from pathlib import Path

from aruntime.backends.base import AgentBackend, BackendExecutionRequest, BackendExecutionResult, EmitEvent
from aruntime.core.models import AgentBackendConfig, AgentBackendType, AgentSpec
from aruntime.executor.task_executor import TaskExecutor
from aruntime.tools.base import ToolExecutionContext, ToolPermissionError


class DirectToolBackend(AgentBackend):
    def __init__(self, config: AgentBackendConfig, dependencies: dict):
        self.config = config
        self.executor: TaskExecutor = dependencies["executor"]
        self.agent_spec: AgentSpec = dependencies["agent_spec"]

    async def prepare(self, request: BackendExecutionRequest) -> None:
        if not request.workspace.workspace_path:
            raise ValueError("workspace_path is required for direct_tool backend")

    async def execute(self, request: BackendExecutionRequest, emit_event: EmitEvent) -> BackendExecutionResult:
        tool_request = request.task_input.get("__tool") if isinstance(request.task_input, dict) else None
        if not isinstance(tool_request, dict) or not tool_request.get("name"):
            return BackendExecutionResult(
                status="FAILED",
                error="direct_tool backend requires task_input.__tool.name",
                backend_type=AgentBackendType.DIRECT_TOOL.value,
            )
        tool_name = str(tool_request["name"])
        allowed_tools = set(self.agent_spec.capability.tools)
        if tool_name not in allowed_tools:
            raise ToolPermissionError(f"tool '{tool_name}' is not allowed for agent '{self.agent_spec.agent_name}'")

        workspace_root = Path(str(request.workspace.workspace_path)).resolve()
        context = ToolExecutionContext(
            workspace_root=workspace_root,
            allowed_roots=[workspace_root],
            allowed_shell_commands=set(),
            timeout_s=float(request.timeout_s),
            max_output_bytes=64 * 1024,
        )
        await emit_event({"name": "tool.started", "tool": tool_name})
        tool_result = await self.executor.execute_tool(tool_name, dict(tool_request.get("arguments") or {}), context)
        await emit_event({"name": "tool.completed", "tool": tool_name, "ok": tool_result.ok})
        return BackendExecutionResult(
            status="SUCCESS" if tool_result.ok else "FAILED",
            output=json.dumps(tool_result.output, ensure_ascii=False),
            error=tool_result.error or "",
            backend_type=AgentBackendType.DIRECT_TOOL.value,
            exit_code=int(tool_result.metadata.get("returncode")) if "returncode" in tool_result.metadata else None,
            usage={"tool": tool_name, "metadata": tool_result.metadata},
        )

    async def cancel(self, attempt_id: str) -> None:
        return None

    async def cleanup(self, request: BackendExecutionRequest) -> None:
        return None
