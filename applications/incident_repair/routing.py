from __future__ import annotations

import hashlib
from typing import Any


def build_idempotency_key(thread_id: str, node_name: str, graph_step: int, logical_item_id: str) -> str:
    raw = f"{thread_id}:{node_name}:{graph_step}:{logical_item_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def coder_tasks(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [task for task in state.get("planned_tasks", []) if task.get("role") == "coder"]


class CoderPlanError(ValueError):
    pass


def validate_coder_plan(planned_tasks: list[dict[str, Any]]) -> None:
    by_id = {task["local_id"]: task for task in planned_tasks}
    coder_items = [task for task in planned_tasks if task.get("role") == "coder"]

    if not coder_items:
        raise CoderPlanError("plan contains no coder tasks")

    for task in coder_items:
        task_id = task["local_id"]
        for dependency_id in task.get("dependencies", []):
            dependency = by_id.get(dependency_id)
            if dependency is None:
                raise CoderPlanError(f"unknown dependency: {task_id}->{dependency_id}")
            if dependency.get("role") != "coder":
                raise CoderPlanError(f"coder task {task_id} depends on non-coder task {dependency_id}")

    _assert_coder_tasks_acyclic(coder_items)


def _assert_coder_tasks_acyclic(coder_items: list[dict[str, Any]]) -> None:
    deps = {task["local_id"]: list(task.get("dependencies", [])) for task in coder_items}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise CoderPlanError("coder dependency graph has cycle")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency_id in deps.get(task_id, []):
            if dependency_id in deps:
                visit(dependency_id)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in deps:
        visit(task_id)


def remaining_coder_tasks(state: dict[str, Any]) -> list[dict[str, Any]]:
    completed = set(state.get("completed_coder_task_ids", []))
    return [
        task
        for task in state.get("planned_tasks", [])
        if task.get("role") == "coder" and task.get("local_id") not in completed
    ]


def ready_coder_tasks(state: dict[str, Any]) -> list[dict[str, Any]]:
    completed = set(state.get("completed_coder_task_ids", []))
    return [task for task in remaining_coder_tasks(state) if set(task.get("dependencies", [])) <= completed]


def choose_next_coder_task(state: dict[str, Any]) -> dict[str, Any] | None:
    ready = ready_coder_tasks(state)
    if not ready:
        return None
    return sorted(ready, key=lambda task: task["local_id"])[0]


def route_after_test(state: dict[str, Any], max_repair_rounds: int = 2) -> str:
    summary = state.get("test_summary")
    if summary is None:
        return "failed"
    if int(summary.get("returncode", 1)) == 0:
        return "reviewer"
    if int(state.get("repair_round", 0)) >= max_repair_rounds:
        return "failed"
    return "repair"


def route_after_review(state: dict[str, Any], max_repair_rounds: int = 2) -> str:
    if state.get("workflow_status") == "FAILED":
        return "failed"
    review = state.get("review_summary") or {}
    if review.get("approved"):
        return "success"
    if int(state.get("repair_round", 0)) >= max_repair_rounds:
        return "failed"
    return "repair"
