from __future__ import annotations

import hashlib
from typing import Any


def build_idempotency_key(thread_id: str, node_name: str, graph_step: int, logical_item_id: str) -> str:
    raw = f"{thread_id}:{node_name}:{graph_step}:{logical_item_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def coder_tasks(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [task for task in state.get("planned_tasks", []) if task.get("role") == "coder"]


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
    review = state.get("review_summary") or {}
    if review.get("approved"):
        return "success"
    if int(state.get("repair_round", 0)) >= max_repair_rounds:
        return "failed"
    return "repair"
