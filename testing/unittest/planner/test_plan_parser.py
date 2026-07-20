from aruntime.planner.models import PlanSpec
from aruntime.planner.parser import normalize_plan_payload
from aruntime.planner.validator import validate_plan


def test_normalize_wrapped_plan_payload():
    payload = {
        "plan": [
            {"id": "fix", "role": "developer", "description": "fix code"},
            {"id": "test", "role": "qa", "description": "run tests", "dependencies": ["fix"]},
            {"id": "review", "role": "review", "description": "review", "dependencies": ["test"]},
        ]
    }

    plan = PlanSpec(**normalize_plan_payload(payload))
    validate_plan(plan)

    assert plan.tasks[0].local_id == "fix"
    assert plan.tasks[0].role == "coder"
    assert plan.tasks[1].role == "tester"
