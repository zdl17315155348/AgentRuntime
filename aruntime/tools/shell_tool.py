from __future__ import annotations

import shlex
import subprocess
from typing import Any

from aruntime.tools.base import ToolExecutionContext, ToolPermissionError, ToolResult, ToolSideEffect, ToolTimeoutError


class RunCommandTool:
    name = "run_command"
    side_effect_level = ToolSideEffect.NONE

    async def execute(self, arguments: dict[str, Any], execution_context: ToolExecutionContext) -> ToolResult:
        command = arguments.get("command")
        if isinstance(command, str):
            argv = shlex.split(command)
        elif isinstance(command, list):
            argv = [str(item) for item in command]
        else:
            return ToolResult(ok=False, error="command missing")
        if not argv:
            return ToolResult(ok=False, error="command missing")
        if execution_context.allowed_shell_commands and argv[0] not in execution_context.allowed_shell_commands:
            raise ToolPermissionError(f"command not allowed: {argv[0]}")
        try:
            proc = subprocess.run(
                argv,
                cwd=str(execution_context.workspace_root),
                capture_output=True,
                text=True,
                timeout=execution_context.timeout_s,
                check=False,
                env={"PATH": "/usr/bin:/bin"},
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolTimeoutError(str(exc)) from exc
        output = (proc.stdout or "")[: execution_context.max_output_bytes]
        error = (proc.stderr or "")[: execution_context.max_output_bytes]
        return ToolResult(ok=proc.returncode == 0, output=output, error=error, metadata={"returncode": proc.returncode})
