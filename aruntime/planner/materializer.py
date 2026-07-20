from __future__ import annotations

from aruntime.core.models import AgentBackendType, FailurePolicy, TaskSpec
from aruntime.planner.models import PlanSpec
from aruntime.planner.validator import validate_plan


ROLE_BACKEND = {
    "coder": AgentBackendType.CODEX_CLI,
    "tester": AgentBackendType.DIRECT_TOOL,
    "reviewer": AgentBackendType.CODEX_CLI,
}


def materialize_plan(parent: TaskSpec, plan: PlanSpec) -> list[TaskSpec]:
    validate_plan(plan)
    id_map = {task.local_id: f"{parent.task_id}:{task.local_id}" for task in plan.tasks}
    planner_context = {
        key: value
        for key, value in (parent.result or {}).items()
        if key in {"inspection", "plan_summary"}
    }
    result: list[TaskSpec] = []
    for item in plan.tasks:
        task_input = {"goal": item.goal}
        if planner_context:
            task_input["planner_context"] = planner_context
        if item.role == "tester":
            task_input = {
                "goal": item.goal,
                **({"planner_context": planner_context} if planner_context else {}),
                "__tool": {
                    "name": "run_pytest",
                    "arguments": {
                        "paths": ["tests"],
                    },
                },
            }
        child = TaskSpec(
            task_id=id_map[item.local_id],
            agent_name=None,
            task_input=task_input,
            context_id=parent.context_id,
            parent_task_id=parent.task_id,
            root_task_id=parent.root_task_id or parent.task_id,
            task_role=item.role,
            required_backend=ROLE_BACKEND[item.role],
            workspace=parent.workspace,
            trace_id=parent.trace_id,
            dependencies=[id_map[dep] for dep in item.dependencies],
            required_capability=item.required_capability,
            resource_request=item.resource_request,
            timeout_ms=item.timeout_ms,
            failure_policy=_role_failure_policy(item.role, item.failure_policy),
        )
        result.append(child)
    return result


def _role_failure_policy(role: str, policy: FailurePolicy) -> FailurePolicy:
    if policy.mode == "fail_open" and role in {"coder", "repair", "tester"}:
        return FailurePolicy(mode="fail_closed", max_retries=policy.max_retries, fallback_agent=policy.fallback_agent, timeout_ms=policy.timeout_ms)
    return policy
