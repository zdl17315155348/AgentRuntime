from __future__ import annotations

from typing import Any

from aruntime.tools.base import Tool, ToolExecutionContext, ToolResult, ToolPermissionError


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(name)
        return self._tools[name]

    async def execute(self, name: str, arguments: dict[str, Any], execution_context: ToolExecutionContext) -> ToolResult:
        tool = self.get(name)
        return await tool.execute(arguments, execution_context)
