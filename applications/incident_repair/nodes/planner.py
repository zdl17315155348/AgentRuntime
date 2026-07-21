from __future__ import annotations

from applications.incident_repair.execution.base import AgentExecutionRequest
from applications.incident_repair.nodes.common import context_from_runtime, execution_record_from_result, load_prompt
from applications.incident_repair.routing import CoderPlanError, build_idempotency_key, validate_coder_plan
from applications.incident_repair.schemas import PlanSpec


async def planner_node(state: dict, runtime):
    context = context_from_runtime(runtime)
    timeout_s = min(int(context.run_config.task_timeout_s), 300)
    request = AgentExecutionRequest(
        run_id=state["run_id"],
        thread_id=state["thread_id"],
        graph_node="planner",
        graph_step=0,
        role="planner",
        backend="deepseek",
        goal=state["user_request"],
        system_prompt=load_prompt("planner.md"),
        source_repo=state["source_repo"],
        base_commit=state["base_commit"],
        timeout_s=timeout_s,
        idempotency_key=build_idempotency_key(state["thread_id"], "planner", 0, "root"),
    )
    result = await context.provider.execute(request)
    if result.status != "SUCCESS":
        return {
            "workflow_status": "FAILED",
            "error": result.error_message or "planner failed",
            "runtime_task_ids": [result.runtime_task_id] if result.runtime_task_id else [],
            "execution_records": [execution_record_from_result(request, result, context.provider.mode)],
        }
    plan = PlanSpec.model_validate(result.structured_result)
    planned_tasks = [task.model_dump() for task in plan.tasks]
    try:
        validate_coder_plan(planned_tasks)
    except CoderPlanError as exc:
        return {
            "workflow_status": "FAILED",
            "error": str(exc),
            "planned_tasks": planned_tasks,
            "runtime_task_ids": [result.runtime_task_id] if result.runtime_task_id else [],
            "execution_records": [execution_record_from_result(request, result, context.provider.mode)],
        }
    return {
        "plan": plan.model_dump(),
        "planned_tasks": planned_tasks,
        "runtime_task_ids": [result.runtime_task_id] if result.runtime_task_id else [],
        "execution_records": [execution_record_from_result(request, result, context.provider.mode)],
    }
