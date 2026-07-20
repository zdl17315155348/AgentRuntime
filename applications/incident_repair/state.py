from __future__ import annotations

import operator
from typing import Annotated, Any
from typing_extensions import TypedDict


def merge_pending_patch_refs(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if right == []:
        return []
    return [*(left or []), *(right or [])]


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


class ExecutionRecord(TypedDict):
    node: str
    role: str
    backend: str
    mode: str
    status: str
    runtime_task_id: str | None
    attempt_ids: list[str]
    queue_wait_ms: float
    setup_ms: float
    backend_ms: float
    cleanup_ms: float
    total_ms: float
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cpu_time_ms: float
    peak_rss_mb: float
    tool_calls: int
    file_reads: int
    search_calls: int


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
    all_patch_refs: Annotated[list[PatchReference], operator.add]
    pending_patch_refs: Annotated[list[PatchReference], merge_pending_patch_refs]
    integrated_commit: str | None
    integration_result: dict[str, Any] | None
    test_summary: TestSummary | None
    review_summary: ReviewSummary | None
    repair_round: int
    workflow_status: str
    error: str | None
    runtime_task_ids: Annotated[list[str], operator.add]
    execution_records: Annotated[list[ExecutionRecord], operator.add]
    event_count: int
    active_coder_task: PlannedTask | None
