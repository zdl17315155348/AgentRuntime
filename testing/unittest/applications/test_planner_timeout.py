from __future__ import annotations

import pytest

from applications.incident_repair.config import ExecutionMode, GraphRuntimeContext, IncidentRunConfig
from applications.incident_repair.execution.base import AgentExecutionResult, ExecutionMetrics
from applications.incident_repair.nodes.planner import planner_node


class _Provider:
    mode = "runtime"

    def __init__(self):
        self.request = None

    async def execute(self, request):
        self.request = request
        return AgentExecutionResult(
            status="FAILED",
            error_message="stop",
            metrics=ExecutionMetrics(submit_started_at=0, execution_started_at=0, execution_finished_at=0),
        )


@pytest.mark.anyio
async def test_planner_uses_configured_task_timeout_without_cap():
    provider = _Provider()
    config = IncidentRunConfig(
        execution_mode=ExecutionMode.RUNTIME,
        run_id="run-timeout",
        thread_id="thread-timeout",
        source_repo=".",
        base_commit="HEAD",
        task_timeout_s=900,
    )
    runtime = GraphRuntimeContext(provider=provider, run_config=config, event_bus=None)

    await planner_node(
        {
            "run_id": config.run_id,
            "thread_id": config.thread_id,
            "user_request": "fix",
            "source_repo": config.source_repo,
            "base_commit": config.base_commit,
        },
        runtime,
    )

    assert provider.request.timeout_s == 900
