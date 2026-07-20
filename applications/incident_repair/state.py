from __future__ import annotations

import operator
from typing import Annotated, Any
from typing_extensions import TypedDict


class PlannedTask(TypedDict):
    local_id: str
    role: str
    goal: str
    dependencies: list[str]


class PatchReference(TypedDict):
    task_local_id: str
    artifact_id: str | None
    patch_path: str
    sha256: str
    changed_files: list[str]


class TestSummary(TypedDict):
    returncode: int
    passed: int
    failed: int
    failed_tests: list[dict[str, Any]]
    report_artifact_id: str | None


class ReviewSummary(TypedDict):
    approved: bool
    requirements_covered: list[str]
    issues: list[str]
    artifact_id: str | None


class IncidentRepairState(TypedDict):
    run_id: str
    thread_id: str
    user_request: str
    source_repo: str
    base_commit: str
    plan: dict[str, Any] | None
    planned_tasks: list[PlannedTask]
    patch_refs: Annotated[list[PatchReference], operator.add]
    integrated_commit: str | None
    test_summary: TestSummary | None
    review_summary: ReviewSummary | None
    repair_round: int
    workflow_status: str
    error: str | None
    runtime_task_ids: Annotated[list[str], operator.add]
    event_count: int
    active_coder_task: PlannedTask | None
