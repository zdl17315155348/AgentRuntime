import json

import pytest

from aruntime.backends.base import BackendExecutionRequest
from aruntime.backends.direct_tool import DirectToolBackend
from aruntime.core.models import AgentBackendConfig, AgentBackendType, AgentCapability, AgentSpec, WorkspaceSpec
from aruntime.executor.task_executor import TaskExecutor
from aruntime.tools.file_tools import ReadFileTool
from aruntime.tools.registry import ToolRegistry


@pytest.mark.anyio
async def test_direct_tool_backend_checks_agent_tools(tmp_path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    agent = AgentSpec(agent_name="tester", role="Tester", capability=AgentCapability(tools=["read_file"]))
    backend = DirectToolBackend(
        AgentBackendConfig(type=AgentBackendType.DIRECT_TOOL),
        {"executor": TaskExecutor(registry), "agent_spec": agent},
    )
    request = BackendExecutionRequest(
        task_id="t1",
        attempt_id="a1",
        agent_name="tester",
        task_input={"__tool": {"name": "read_file", "arguments": {"path": "a.txt"}}},
        workspace=WorkspaceSpec(source_repo=str(tmp_path), workspace_path=str(tmp_path)),
    )
    events = []

    async def emit(event):
        events.append(event)

    result = await backend.execute(request, emit)

    assert result.status == "SUCCESS"
    assert json.loads(result.output) == "hello"
    assert events[-1]["name"] == "tool.completed"
