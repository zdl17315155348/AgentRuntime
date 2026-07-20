from __future__ import annotations

import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Any

from aruntime.tools.base import ToolExecutionContext, ToolResult, ToolSideEffect, ToolTimeoutError


class RunPytestTool:
    name = "run_pytest"
    side_effect_level = ToolSideEffect.NONE

    async def execute(self, arguments: dict[str, Any], execution_context: ToolExecutionContext) -> ToolResult:
        started = time.perf_counter()
        extra_args = arguments.get("args", [])
        if not isinstance(extra_args, list):
            extra_args = []
        paths = arguments.get("paths", [])
        if not isinstance(paths, list):
            paths = []
        argv = ["python3", "-m", "pytest", *[str(arg) for arg in extra_args], *[str(path) for path in paths]]
        junit_xml = arguments.get("junit_xml")
        if isinstance(junit_xml, str) and junit_xml:
            argv.append(f"--junitxml={junit_xml}")
        try:
            proc = subprocess.run(
                argv,
                cwd=str(execution_context.workspace_root),
                capture_output=True,
                text=True,
                timeout=execution_context.timeout_s,
                check=False,
                env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_ADDOPTS": "-p no:cacheprovider"},
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolTimeoutError(str(exc)) from exc
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        parsed = _parse_pytest_output(proc.stdout or "", junit_xml if isinstance(junit_xml, str) else "")
        return ToolResult(
            ok=proc.returncode == 0,
            output={
                "returncode": proc.returncode,
                "passed": parsed["passed"],
                "failed": parsed["failed"],
                "duration_ms": duration_ms,
                "failed_tests": parsed["failed_tests"],
                "stdout": (proc.stdout or "")[: execution_context.max_output_bytes],
            },
            error=(proc.stderr or "")[: execution_context.max_output_bytes],
            metadata={"returncode": proc.returncode, "duration_ms": duration_ms},
        )


def _parse_pytest_output(stdout: str, junit_xml: str) -> dict[str, Any]:
    result: dict[str, Any] = {"passed": 0, "failed": 0, "failed_tests": []}
    if junit_xml:
        try:
            root = ET.parse(junit_xml).getroot()
            suites = list(root.iter("testsuite")) if root.tag == "testsuites" else [root]
            result["failed"] = sum(int(suite.attrib.get("failures", "0")) + int(suite.attrib.get("errors", "0")) for suite in suites)
            total = sum(int(suite.attrib.get("tests", "0")) for suite in suites)
            skipped = sum(int(suite.attrib.get("skipped", "0")) for suite in suites)
            result["passed"] = max(total - result["failed"] - skipped, 0)
            failed_tests = []
            for case in root.iter("testcase"):
                failures = case.findall("failure") + case.findall("error")
                failure = failures[0] if failures else None
                if failure is not None:
                    failed_tests.append(
                        {
                            "name": f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}".strip(":"),
                            "message": (failure.attrib.get("message") or failure.text or "")[:512],
                        }
                    )
            result["failed_tests"] = failed_tests
            return result
        except Exception:
            pass
    for marker, key in ((" passed", "passed"), (" failed", "failed"), (" error", "failed")):
        for part in stdout.replace(",", " ").split():
            if part.isdigit() and marker.strip() in stdout:
                result[key] = max(result[key], int(part))
                break
    return result
