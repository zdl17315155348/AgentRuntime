from __future__ import annotations

from aruntime.planner.models import PlanSpec


def validate_plan(plan: PlanSpec) -> None:
    if len(plan.tasks) < 2 or len(plan.tasks) > 12:
        raise ValueError("plan must contain 2 to 12 tasks")
    ids = [task.local_id for task in plan.tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("local_id must be unique")
    known = set(ids)
    roles = {task.role for task in plan.tasks}
    if "coder" not in roles:
        raise ValueError("plan must include at least one coder")
    if "tester" not in roles:
        raise ValueError("plan must include tester")
    if "reviewer" not in roles:
        raise ValueError("plan must include reviewer")
    for task in plan.tasks:
        for dep in task.dependencies:
            if dep not in known:
                raise ValueError(f"dependency not found: {dep}")
        if task.role == "tester":
            for dep in task.dependencies:
                dep_task = next(item for item in plan.tasks if item.local_id == dep)
                if dep_task.role == "reviewer":
                    raise ValueError("tester cannot depend on reviewer")
        if task.role == "reviewer":
            cap = task.required_capability or {}
            if cap.get("can_code") or cap.get("can_test"):
                raise ValueError("reviewer cannot request write/test capability")
        for forbidden in ("agent_name", "workspace_path", "api_key", "env"):
            if forbidden in task.required_capability or forbidden in task.resource_request:
                raise ValueError(f"planner cannot specify {forbidden}")
    _assert_acyclic(plan)


def _assert_acyclic(plan: PlanSpec) -> None:
    deps = {task.local_id: list(task.dependencies) for task in plan.tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError("plan dependency graph has cycle")
        if node in visited:
            return
        visiting.add(node)
        for dep in deps[node]:
            visit(dep)
        visiting.remove(node)
        visited.add(node)

    for node in deps:
        visit(node)
