from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentExecutionRequest(BaseModel):
    run_id: str
    thread_id: str
    graph_node: str
    graph_step: int
    role: Literal["planner", "coder", "tester", "repair", "reviewer"]
    backend: Literal["deepseek", "codex_cli", "direct_tool"]
    goal: str
    system_prompt: str = ""
    task_input: dict[str, Any] = Field(default_factory=dict)
    source_repo: str
    base_commit: str
    workspace_path: str | None = None
    context_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    timeout_s: int = 300
    idempotency_key: str
    resource_request: dict[str, Any] = Field(default_factory=dict)


class ExecutionMetrics(BaseModel):
    submit_started_at: float
    execution_started_at: float
    execution_finished_at: float
    queue_wait_ms: float = 0
    setup_ms: float = 0
    backend_ms: float = 0
    cleanup_ms: float = 0
    total_ms: float = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cpu_time_ms: float = 0
    peak_rss_mb: float = 0
    tool_calls: int = 0
    file_reads: int = 0
    search_calls: int = 0


class AgentExecutionResult(BaseModel):
    status: Literal["SUCCESS", "FAILED", "TIMEOUT", "CANCELLED"]
    output: str = ""
    error_type: str | None = None
    error_message: str | None = None
    runtime_task_id: str | None = None
    attempt_ids: list[str] = Field(default_factory=list)
    workspace_path: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    patch_ref: dict[str, Any] | None = None
    structured_result: dict[str, Any] = Field(default_factory=dict)
    metrics: ExecutionMetrics


class ExecutionProvider(ABC):
    @property
    @abstractmethod
    def mode(self) -> str:
        ...

    @abstractmethod
    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        ...

    @abstractmethod
    async def cancel_run(self, run_id: str) -> None:
        ...

    @abstractmethod
    async def inject_fault(self, run_id: str, target: dict[str, Any]) -> dict[str, Any]:
        ...

    @abstractmethod
    async def get_execution_snapshot(self, run_id: str) -> dict[str, Any]:
        ...
