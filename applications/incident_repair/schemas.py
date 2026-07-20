from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlannedTaskModel(BaseModel):
    local_id: str
    role: str
    goal: str
    dependencies: list[str] = Field(default_factory=list)


class PlanSpec(BaseModel):
    version: str = "1.0"
    summary: str = ""
    tasks: list[PlannedTaskModel] = Field(default_factory=list)


class TestSummaryModel(BaseModel):
    returncode: int = 0
    passed: int = 0
    failed: int = 0
    failed_tests: list[dict[str, Any]] = Field(default_factory=list)
    report_artifact_id: str | None = None


class CoderResultModel(BaseModel):
    completed: bool
    summary: str
    tests_run: list[str] = Field(default_factory=list)
    remaining_issues: list[str] = Field(default_factory=list)


class ReviewSummaryModel(BaseModel):
    approved: bool = False
    requirements_covered: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    summary: str = ""
    artifact_id: str | None = None
