from __future__ import annotations

from pydantic import BaseModel, Field

from aruntime.core.models import ArtifactReference


class RecoveryContext(BaseModel):
    previous_attempt_id: str
    previous_agent: str
    failure_reason: str
    completed_events: list[dict] = Field(default_factory=list)
    partial_patch: ArtifactReference | None = None
    changed_files: list[str] = Field(default_factory=list)
    shared_context_version: int | None = None
