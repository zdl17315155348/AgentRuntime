from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, Field

from aruntime.core.models import ArtifactReference, WorkspaceSpec


EmitEvent = Callable[[dict[str, Any]], Awaitable[None]]


class BackendExecutionRequest(BaseModel):
    task_id: str
    attempt_id: str
    agent_name: str
    system_prompt: str = ""
    user_message: str = ""
    task_input: dict[str, Any] = Field(default_factory=dict)
    workspace: WorkspaceSpec
    runtime_context: dict[str, Any] = Field(default_factory=dict)
    timeout_s: int = 300
    token_budget: Optional[int] = None


class BackendExecutionResult(BaseModel):
    status: Literal["SUCCESS", "FAILED", "CANCELLED", "TIMEOUT"]
    output: str = ""
    error: str = ""
    backend_type: str
    backend_session_id: Optional[str] = None
    backend_run_id: Optional[str] = None
    backend_pid: Optional[int] = None
    exit_code: Optional[int] = None
    usage: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactReference] = Field(default_factory=list)


class AgentBackend(ABC):
    @abstractmethod
    async def prepare(self, request: BackendExecutionRequest) -> None:
        ...

    @abstractmethod
    async def execute(self, request: BackendExecutionRequest, emit_event: EmitEvent) -> BackendExecutionResult:
        ...

    @abstractmethod
    async def cancel(self, attempt_id: str) -> None:
        ...

    @abstractmethod
    async def cleanup(self, request: BackendExecutionRequest) -> None:
        ...
