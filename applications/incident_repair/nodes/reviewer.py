from __future__ import annotations

from applications.incident_repair.execution.base import AgentExecutionRequest
from applications.incident_repair.nodes.common import context_from_runtime, execution_record_from_result, load_prompt
from applications.incident_repair.routing import build_idempotency_key
from applications.incident_repair.schemas import ReviewSummaryModel


async def reviewer_node(state: dict, runtime):
    context = context_from_runtime(runtime)
    request = AgentExecutionRequest(
        run_id=state["run_id"],
        thread_id=state["thread_id"],
        graph_node="reviewer",
        graph_step=20 + int(state.get("repair_round", 0)),
        role="reviewer",
        backend="codex_cli",
        goal=state["user_request"],
        system_prompt=load_prompt("reviewer.md"),
        task_input={"test_summary": state.get("test_summary"), "patch_refs": state.get("patch_refs", [])},
        source_repo=state["source_repo"],
        base_commit=state.get("integrated_commit") or state["base_commit"],
        timeout_s=180,
        idempotency_key=build_idempotency_key(state["thread_id"], "reviewer", 20 + int(state.get("repair_round", 0)), "root"),
    )
    result = await context.provider.execute(request)
    if result.status != "SUCCESS":
        return {"workflow_status": "FAILED", "error": result.error_message or "reviewer failed"}
    review = ReviewSummaryModel.model_validate(result.structured_result)
    return {
        "review_summary": review.model_dump(),
        "runtime_task_ids": [result.runtime_task_id] if result.runtime_task_id else [],
        "execution_records": [execution_record_from_result(request, result, context.provider.mode)],
    }
