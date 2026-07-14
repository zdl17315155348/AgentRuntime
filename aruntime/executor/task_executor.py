from __future__ import annotations

from typing import Any

from aruntime.tools.base import ToolExecutionContext, ToolPermissionError, ToolResult, ToolSideEffect, ToolTimeoutError
from aruntime.tools.registry import ToolRegistry


class TaskExecutor:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def execute_tool(self, name: str, arguments: dict[str, Any], execution_context: ToolExecutionContext) -> ToolResult:
        result = await self.registry.execute(name, arguments, execution_context)
        execution_context.trace.append({"tool": name, "ok": result.ok})
        return result
