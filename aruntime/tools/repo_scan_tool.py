from __future__ import annotations

from typing import Any

from aruntime.tools.base import ToolExecutionContext, ToolResult, ToolSideEffect


class RepoScanTool:
    name = "repo_scan"
    side_effect_level = ToolSideEffect.NONE

    async def execute(self, arguments: dict[str, Any], execution_context: ToolExecutionContext) -> ToolResult:
        root = execution_context.workspace_root
        files = [str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()]
        return ToolResult(ok=True, output=files[:1000])
