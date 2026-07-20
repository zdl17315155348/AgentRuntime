from __future__ import annotations

from pathlib import Path
from typing import Any

from aruntime.tools.base import ToolExecutionContext
from aruntime.tools.pytest_tool import RunPytestTool


async def run_pytest_direct(workspace_path: str, timeout_s: int, junit_xml: str = "pytest.xml") -> dict[str, Any]:
    tool = RunPytestTool()
    result = await tool.execute(
        {"junit_xml": junit_xml},
        ToolExecutionContext(workspace_root=Path(workspace_path), timeout_s=timeout_s, max_output_bytes=65536),
    )
    output = result.output if isinstance(result.output, dict) else {}
    output.setdefault("report_artifact_id", None)
    return output
