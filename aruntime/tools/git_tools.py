from __future__ import annotations

import subprocess
from typing import Any

from aruntime.tools.base import ToolExecutionContext, ToolPermissionError, ToolResult, ToolSideEffect


class GitStatusTool:
    name = "git_status"
    side_effect_level = ToolSideEffect.NONE

    async def execute(self, arguments: dict[str, Any], execution_context: ToolExecutionContext) -> ToolResult:
        proc = subprocess.run(
            ["git", "-C", str(execution_context.workspace_root), "status", "--short"],
            capture_output=True,
            text=True,
            timeout=execution_context.timeout_s,
            check=False,
        )
        return ToolResult(ok=proc.returncode == 0, output=proc.stdout.strip(), error=proc.stderr.strip())


class GitDiffTool:
    name = "git_diff"
    side_effect_level = ToolSideEffect.NONE

    async def execute(self, arguments: dict[str, Any], execution_context: ToolExecutionContext) -> ToolResult:
        proc = subprocess.run(
            ["git", "-C", str(execution_context.workspace_root), "diff", "--no-ext-diff", "--unified=3"],
            capture_output=True,
            text=True,
            timeout=execution_context.timeout_s,
            check=False,
        )
        return ToolResult(ok=proc.returncode == 0, output=proc.stdout[: execution_context.max_output_bytes], error=proc.stderr.strip())
