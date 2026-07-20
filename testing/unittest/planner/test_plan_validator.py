import pytest

from aruntime.planner.models import PlanSpec, PlanTask
from aruntime.planner.validator import validate_plan


def test_valid_plan_passes():
    plan = PlanSpec(
        summary="x",
        tasks=[
            PlanTask(local_id="fix", role="coder", goal="fix"),
            PlanTask(local_id="test", role="tester", goal="test", dependencies=["fix"]),
            PlanTask(local_id="review", role="reviewer", goal="review", dependencies=["test"]),
        ],
    )

    validate_plan(plan)


def test_cycle_rejected():
    plan = PlanSpec(
        summary="x",
        tasks=[
            PlanTask(local_id="fix", role="coder", goal="fix", dependencies=["review"]),
            PlanTask(local_id="test", role="tester", goal="test", dependencies=["fix"]),
            PlanTask(local_id="review", role="reviewer", goal="review", dependencies=["test"]),
        ],
    )

    with pytest.raises(ValueError):
        validate_plan(plan)
