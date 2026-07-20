from __future__ import annotations

import pytest

from applications.incident_repair.config import ExecutionMode, GraphRuntimeContext, IncidentRunConfig
from applications.incident_repair.execution.base import AgentExecutionRequest, AgentExecutionResult, ExecutionMetrics, ExecutionProvider
from applications.incident_repair.nodes.repair import repair_node


class _Provider(ExecutionProvider):
    @property
    def mode(self):
        return "direct"

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        return AgentExecutionResult(status="SUCCESS", metrics=ExecutionMetrics(submit_started_at=0, execution_started_at=0, execution_finished_at=0))

    async def cancel_run(self, run_id: str) -> None:
        return None

    async def inject_fault(self, run_id: str, target: dict):
        return {}

    async def get_execution_snapshot(self, run_id: str):
        return {}


@pytest.mark.anyio
async def test_repair_without_patch_fails_workflow():
    context = GraphRuntimeContext(
        provider=_Provider(),
        run_config=IncidentRunConfig(execution_mode=ExecutionMode.DIRECT, run_id="r", thread_id="t", source_repo=".", base_commit="HEAD"),
        event_bus=None,
    )

    result = await repair_node(
        {
            "run_id": "r",
            "thread_id": "t",
            "user_request": "fix",
            "source_repo": ".",
            "base_commit": "HEAD",
            "integrated_commit": None,
            "repair_round": 0,
            "test_summary": {"returncode": 1},
            "patch_refs": [],
        },
        context,
    )

    assert result["workflow_status"] == "FAILED"
    assert result["error"] == "repair produced no patch"
