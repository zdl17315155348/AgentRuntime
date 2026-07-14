from __future__ import annotations

import subprocess
from typing import Any

from aruntime.tools.base import ToolExecutionContext, ToolResult, ToolSideEffect, ToolTimeoutError


class RunPytestTool:
    name = "run_pytest"
    side_effect_level = ToolSideEffect.NONE

    async def execute(self, arguments: dict[str, Any], execution_context: ToolExecutionContext) -> ToolResult:
        extra_args = arguments.get("args", [])
        if not isinstance(extra_args, list):
            extra_args = []
        argv = ["python3", "-m", "pytest", *[str(arg) for arg in extra_args]]
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
        return ToolResult(
            ok=proc.returncode == 0,
            output=(proc.stdout or "")[: execution_context.max_output_bytes],
            error=(proc.stderr or "")[: execution_context.max_output_bytes],
            metadata={"returncode": proc.returncode},
        )
