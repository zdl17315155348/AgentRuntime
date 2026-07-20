import json

import pytest

from aruntime.backends.base import BackendExecutionRequest
from aruntime.backends.native_planner import NativePlannerBackend
from aruntime.core.models import AgentBackendConfig, AgentBackendType, AgentCapability, AgentSpec, WorkspaceSpec
from aruntime.executor.task_executor import TaskExecutor
from aruntime.llm.gateway import LLMResult
from aruntime.tools.file_tools import ReadFileTool, SearchCodeTool
from aruntime.tools.registry import ToolRegistry
from aruntime.tools.repo_scan_tool import RepoScanTool


class PlannerLLM:
    backend = "mock"

    def __init__(self):
        self.calls = 0

    def chat_with_stats(self, system_prompt, user_message, prefix_cache_hit=False):
        self.calls += 1
        if self.calls == 1:
            output = json.dumps({"files": ["app.py"], "searches": [{"query": "bug", "path": "."}], "summary": "inspect"})
        else:
            output = json.dumps(
                {
                    "version": "1.0",
                    "summary": "plan",
                    "tasks": [
                        {"local_id": "fix", "role": "coder", "goal": "fix bug"},
                        {"local_id": "test", "role": "tester", "goal": "run tests", "dependencies": ["fix"]},
                        {"local_id": "review", "role": "reviewer", "goal": "review", "dependencies": ["test"]},
                    ],
                }
            )
        return LLMResult(output=output, input_tokens=1, output_tokens=1, total_tokens=2, latency_ms=1)


class EmptyInspectionLLM(PlannerLLM):
    def chat_with_stats(self, system_prompt, user_message, prefix_cache_hit=False):
        self.calls += 1
        if self.calls == 1:
            output = json.dumps({"files": [], "searches": [], "summary": ""})
        else:
            output = json.dumps(
                {
                    "version": "1.0",
                    "summary": "plan",
                    "tasks": [
                        {"local_id": "fix", "role": "coder", "goal": "fix bug"},
                        {"local_id": "test", "role": "tester", "goal": "run tests", "dependencies": ["fix"]},
                        {"local_id": "review", "role": "reviewer", "goal": "review", "dependencies": ["test"]},
                    ],
                }
            )
        return LLMResult(output=output, input_tokens=1, output_tokens=1, total_tokens=2, latency_ms=1)


@pytest.mark.anyio
async def test_native_planner_scans_inspects_and_returns_plan(tmp_path):
    (tmp_path / "app.py").write_text("# bug\n", encoding="utf-8")
    registry = ToolRegistry()
    for tool in (RepoScanTool(), ReadFileTool(), SearchCodeTool()):
        registry.register(tool)
    backend = NativePlannerBackend(
        AgentBackendConfig(type=AgentBackendType.NATIVE_PLANNER),
        {"llm_gateway": PlannerLLM(), "executor": TaskExecutor(registry), "agent_spec": AgentSpec(agent_name="architect", role="Architect", capability=AgentCapability(can_plan=True))},
    )
    request = BackendExecutionRequest(
        task_id="root",
        attempt_id="root:attempt:1",
        agent_name="architect",
        task_input={"request": "fix"},
        workspace=WorkspaceSpec(source_repo=str(tmp_path), workspace_path=str(tmp_path)),
    )
    events = []

    async def emit(event):
        events.append(event)

    result = await backend.execute(request, emit)

    assert result.status == "SUCCESS"
    payload = json.loads(result.output)
    assert payload["plan"]["tasks"][0]["role"] == "coder"
    assert events[0]["name"] == "planner.repo_scan"


@pytest.mark.anyio
async def test_native_planner_falls_back_to_repo_scan_files(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "auth.py").write_text("# auth\n", encoding="utf-8")
    (tmp_path / "app" / "orders.py").write_text("# orders\n", encoding="utf-8")
    (tmp_path / "tests" / "test_auth.py").write_text("# tests\n", encoding="utf-8")
    registry = ToolRegistry()
    for tool in (RepoScanTool(), ReadFileTool(), SearchCodeTool()):
        registry.register(tool)
    backend = NativePlannerBackend(
        AgentBackendConfig(type=AgentBackendType.NATIVE_PLANNER),
        {"llm_gateway": EmptyInspectionLLM(), "executor": TaskExecutor(registry), "agent_spec": AgentSpec(agent_name="architect", role="Architect", capability=AgentCapability(can_plan=True))},
    )
    request = BackendExecutionRequest(
        task_id="root",
        attempt_id="root:attempt:1",
        agent_name="architect",
        task_input={"request": "fix"},
        workspace=WorkspaceSpec(source_repo=str(tmp_path), workspace_path=str(tmp_path)),
    )

    async def emit(event):
        return None

    result = await backend.execute(request, emit)

    payload = json.loads(result.output)
    assert payload["inspection"]["files"][:2] == ["app/auth.py", "app/orders.py"]
