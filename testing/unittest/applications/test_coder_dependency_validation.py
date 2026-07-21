from __future__ import annotations

import pytest

from applications.incident_repair.routing import CoderPlanError, validate_coder_plan


def test_coder_plan_accepts_coder_dependencies():
    validate_coder_plan(
        [
            {"local_id": "b", "role": "coder", "goal": "fix b", "dependencies": []},
            {"local_id": "a", "role": "coder", "goal": "fix a", "dependencies": ["b"]},
            {"local_id": "t", "role": "tester", "goal": "test", "dependencies": ["a"]},
        ]
    )


def test_coder_plan_rejects_missing_coder_tasks():
    with pytest.raises(CoderPlanError, match="plan contains no coder tasks"):
        validate_coder_plan([{"local_id": "t", "role": "tester", "goal": "test", "dependencies": []}])


def test_coder_plan_rejects_unknown_dependency():
    with pytest.raises(CoderPlanError, match="unknown dependency: a->missing"):
        validate_coder_plan([{"local_id": "a", "role": "coder", "goal": "fix", "dependencies": ["missing"]}])


def test_coder_plan_rejects_non_coder_dependency():
    with pytest.raises(CoderPlanError, match="depends on non-coder task"):
        validate_coder_plan(
            [
                {"local_id": "t", "role": "tester", "goal": "test", "dependencies": []},
                {"local_id": "a", "role": "coder", "goal": "fix", "dependencies": ["t"]},
            ]
        )


def test_coder_plan_rejects_cycle():
    with pytest.raises(CoderPlanError, match="coder dependency graph has cycle"):
        validate_coder_plan(
            [
                {"local_id": "a", "role": "coder", "goal": "fix a", "dependencies": ["b"]},
                {"local_id": "b", "role": "coder", "goal": "fix b", "dependencies": ["a"]},
            ]
        )
