from __future__ import annotations

from applications.incident_repair.execution.base import AgentExecutionRequest
from applications.incident_repair.nodes.common import context_from_runtime, execution_record_from_result
from applications.incident_repair.routing import build_idempotency_key
from applications.incident_repair.schemas import TestSummaryModel


async def tester_node(state: dict, runtime):
    context = context_from_runtime(runtime)
    request = AgentExecutionRequest(
        run_id=state["run_id"],
        thread_id=state["thread_id"],
        graph_node="tester",
        graph_step=3 + int(state.get("repair_round", 0)),
        role="tester",
        backend="direct_tool",
        goal="run pytest",
        task_input={"integrated_commit": state.get("integrated_commit")},
        source_repo=state["source_repo"],
        base_commit=state.get("integrated_commit") or state["base_commit"],
        timeout_s=180,
        idempotency_key=build_idempotency_key(state["thread_id"], "tester", 3 + int(state.get("repair_round", 0)), "root"),
    )
    result = await context.provider.execute(request)
    summary = TestSummaryModel.model_validate(result.structured_result)
    return {
        "test_summary": summary.model_dump(),
        "runtime_task_ids": [result.runtime_task_id] if result.runtime_task_id else [],
        "execution_records": [execution_record_from_result(request, result, context.provider.mode)],
    }
