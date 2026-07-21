from __future__ import annotations

from applications.incident_repair.nodes.select_coder import route_after_select, select_coder_node
from applications.incident_repair.routing import choose_next_coder_task, ready_coder_tasks, remaining_coder_tasks


def test_two_independent_coders_run_in_fixed_id_order():
    state = {
        "planned_tasks": [
            {"local_id": "b", "role": "coder", "goal": "fix b", "dependencies": []},
            {"local_id": "a", "role": "coder", "goal": "fix a", "dependencies": []},
        ],
        "completed_coder_task_ids": [],
    }

    assert [task["local_id"] for task in ready_coder_tasks(state)] == ["b", "a"]
    assert choose_next_coder_task(state)["local_id"] == "a"


def test_dependency_makes_prerequisite_run_first():
    state = {
        "planned_tasks": [
            {"local_id": "a", "role": "coder", "goal": "fix a", "dependencies": ["b"]},
            {"local_id": "b", "role": "coder", "goal": "fix b", "dependencies": []},
        ],
        "completed_coder_task_ids": [],
    }

    assert choose_next_coder_task(state)["local_id"] == "b"


def test_select_skips_completed_task_after_checkpoint_restore():
    state = {
        "planned_tasks": [
            {"local_id": "a", "role": "coder", "goal": "fix a", "dependencies": []},
            {"local_id": "b", "role": "coder", "goal": "fix b", "dependencies": ["a"]},
        ],
        "completed_coder_task_ids": ["a"],
        "coder_step": 1,
    }

    assert [task["local_id"] for task in remaining_coder_tasks(state)] == ["b"]
    update = select_coder_node(state)
    assert update["active_coder_task"]["local_id"] == "b"
    assert update["coder_step"] == 2
    assert route_after_select({**state, **update}) == "coder"


def test_select_routes_to_tester_when_no_coders_remain():
    state = {
        "planned_tasks": [{"local_id": "a", "role": "coder", "goal": "fix a", "dependencies": []}],
        "completed_coder_task_ids": ["a"],
    }

    update = select_coder_node(state)
    assert update == {"active_coder_task": None}
    assert route_after_select({**state, **update}) == "tester"


def test_select_fails_unresolved_dependency_graph():
    state = {
        "planned_tasks": [{"local_id": "a", "role": "coder", "goal": "fix a", "dependencies": ["missing"]}],
        "completed_coder_task_ids": [],
    }

    update = select_coder_node(state)
    assert update["workflow_status"] == "FAILED"
    assert route_after_select({**state, **update}) == "failed"


def test_select_preserves_failed_workflow_status():
    state = {
        "workflow_status": "FAILED",
        "planned_tasks": [{"local_id": "a", "role": "coder", "goal": "fix a", "dependencies": []}],
        "completed_coder_task_ids": [],
    }

    update = select_coder_node(state)
    assert update == {"active_coder_task": None}
    assert route_after_select({**state, **update}) == "failed"
