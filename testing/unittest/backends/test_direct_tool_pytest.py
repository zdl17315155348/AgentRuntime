import json

import pytest

from aruntime.backends.base import BackendExecutionRequest
from aruntime.backends.direct_tool import DirectToolBackend
from aruntime.core.models import AgentBackendConfig, AgentBackendType, AgentCapability, AgentSpec, WorkspaceSpec
from aruntime.executor.task_executor import TaskExecutor
from aruntime.tools.pytest_tool import RunPytestTool
from aruntime.tools.registry import ToolRegistry


@pytest.mark.anyio
async def test_direct_tool_pytest_returns_structured_result(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(RunPytestTool())
    agent = AgentSpec(agent_name="tester", role="Tester", capability=AgentCapability(tools=["run_pytest"]))
    backend = DirectToolBackend(
        AgentBackendConfig(type=AgentBackendType.DIRECT_TOOL),
        {"executor": TaskExecutor(registry), "agent_spec": agent},
    )
    request = BackendExecutionRequest(
        task_id="t1",
        attempt_id="a1",
        agent_name="tester",
        task_input={"__tool": {"name": "run_pytest", "arguments": {"paths": ["tests"], "junit_xml": str(tmp_path / "pytest.xml")}}},
        workspace=WorkspaceSpec(source_repo=str(tmp_path), workspace_path=str(tmp_path)),
        timeout_s=10,
    )

    async def emit(event):
        return None

    result = await backend.execute(request, emit)
    payload = json.loads(result.output)

    assert result.status == "SUCCESS"
    assert payload["returncode"] == 0
    assert payload["passed"] == 1
