from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal

from aruntime.core.models import FailurePolicy


class SearchRequest(BaseModel):
    query: str
    path: str = "."


class InspectionRequest(BaseModel):
    files: list[str] = Field(default_factory=list)
    searches: list[SearchRequest] = Field(default_factory=list)
    summary: str = ""


class PlanTask(BaseModel):
    local_id: str
    role: Literal["coder", "tester", "reviewer"]
    goal: str
    dependencies: list[str] = Field(default_factory=list)
    required_capability: dict = Field(default_factory=dict)
    resource_request: dict = Field(default_factory=dict)
    timeout_ms: int = 300000
    failure_policy: FailurePolicy = Field(default_factory=FailurePolicy)


class PlanSpec(BaseModel):
    version: Literal["1.0"] = "1.0"
    summary: str
    tasks: list[PlanTask]
