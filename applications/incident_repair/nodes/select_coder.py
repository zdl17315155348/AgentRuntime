from __future__ import annotations

from applications.incident_repair.routing import choose_next_coder_task, remaining_coder_tasks


def select_coder_node(state: dict, runtime=None):
    if state.get("workflow_status") == "FAILED":
        return {"active_coder_task": None}

    remaining = remaining_coder_tasks(state)
    if not remaining:
        return {"active_coder_task": None}

    task = choose_next_coder_task(state)
    if task is None:
        return {
            "workflow_status": "FAILED",
            "error": "no ready coder task; dependency graph is unresolved",
            "active_coder_task": None,
        }

    return {
        "active_coder_task": task,
        "coder_step": int(state.get("coder_step", 0)) + 1,
    }


def route_after_select(state: dict) -> str:
    if state.get("workflow_status") == "FAILED":
        return "failed"
    if state.get("active_coder_task"):
        return "coder"
    return "tester"
