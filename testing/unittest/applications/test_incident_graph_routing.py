from __future__ import annotations

from applications.incident_repair.routing import build_idempotency_key, coder_tasks, route_after_review, route_after_test


def test_idempotency_key_is_stable_and_scope_sensitive():
    first = build_idempotency_key("thread", "coder", 1, "auth")
    assert first == build_idempotency_key("thread", "coder", 1, "auth")
    assert first != build_idempotency_key("thread", "coder", 1, "orders")


def test_coder_tasks_filters_planner_output():
    state = {"planned_tasks": [{"role": "coder", "local_id": "a"}, {"role": "tester", "local_id": "t"}]}
    assert coder_tasks(state) == [{"role": "coder", "local_id": "a"}]


def test_tester_route_success_failure_and_repair_limit():
    assert route_after_test({"test_summary": {"returncode": 0}, "repair_round": 0}) == "reviewer"
    assert route_after_test({"test_summary": {"returncode": 1}, "repair_round": 0}) == "repair"
    assert route_after_test({"test_summary": {"returncode": 1}, "repair_round": 2}) == "failed"
    assert route_after_test({"test_summary": None}) == "failed"


def test_review_route_respects_repair_limit():
    assert route_after_review({"review_summary": {"approved": True}, "repair_round": 0}) == "success"
    assert route_after_review({"review_summary": {"approved": False}, "repair_round": 0}) == "repair"
    assert route_after_review({"review_summary": {"approved": False}, "repair_round": 2}) == "failed"
