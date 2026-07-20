from __future__ import annotations

from applications.incident_repair.execution.base import AgentExecutionRequest
from applications.incident_repair.nodes.common import context_from_runtime, load_prompt
from applications.incident_repair.routing import build_idempotency_key
from applications.incident_repair.schemas import PlanSpec


async def planner_node(state: dict, runtime):
    context = context_from_runtime(runtime)
    result = await context.provider.execute(
        AgentExecutionRequest(
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
            timeout_s=120,
            idempotency_key=build_idempotency_key(state["thread_id"], "planner", 0, "root"),
        )
    )
    plan = PlanSpec.model_validate(result.structured_result)
    return {
        "plan": plan.model_dump(),
        "planned_tasks": [task.model_dump() for task in plan.tasks],
        "runtime_task_ids": [result.runtime_task_id] if result.runtime_task_id else [],
    }
