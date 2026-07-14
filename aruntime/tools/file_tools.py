from __future__ import annotations

from pathlib import Path
from typing import Any

from aruntime.tools.base import ToolExecutionContext, ToolPermissionError, ToolResult, ToolSideEffect


class ReadFileTool:
    name = "read_file"
    side_effect_level = ToolSideEffect.NONE

    async def execute(self, arguments: dict[str, Any], execution_context: ToolExecutionContext) -> ToolResult:
        path = execution_context.resolve_path(str(arguments.get("path", "")))
        if not path.is_file():
            return ToolResult(ok=False, error="file not found")
        content = path.read_bytes()[: execution_context.max_output_bytes]
        return ToolResult(ok=True, output=content.decode("utf-8", errors="replace"))


class WriteFileTool:
    name = "write_file"
    side_effect_level = ToolSideEffect.FILE_WRITE

    async def execute(self, arguments: dict[str, Any], execution_context: ToolExecutionContext) -> ToolResult:
        path = execution_context.resolve_path(str(arguments.get("path", "")))
        content = str(arguments.get("content", ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return ToolResult(ok=True, output={"path": str(path)})


class SearchCodeTool:
    name = "search_code"
    side_effect_level = ToolSideEffect.NONE

    async def execute(self, arguments: dict[str, Any], execution_context: ToolExecutionContext) -> ToolResult:
        needle = str(arguments.get("needle", ""))
        path = execution_context.resolve_path(str(arguments.get("path", ".")))
        matches: list[str] = []
        for file in path.rglob("*"):
            if not file.is_file():
                continue
            try:
                text = file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if needle in text:
                matches.append(str(file.relative_to(execution_context.workspace_root)))
        return ToolResult(ok=True, output=matches)
