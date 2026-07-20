from __future__ import annotations

from pathlib import Path
from typing import Any

from applications.incident_repair.execution.base import AgentExecutionRequest, AgentExecutionResult


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def context_from_runtime(runtime):
    return getattr(runtime, "context", runtime)


def execution_record_from_result(request: AgentExecutionRequest, result: AgentExecutionResult, mode: str) -> dict[str, Any]:
    metrics = result.metrics
    return {
        "node": request.graph_node,
        "role": request.role,
        "backend": request.backend,
        "mode": mode,
        "status": result.status,
        "runtime_task_id": result.runtime_task_id,
        "attempt_ids": result.attempt_ids,
        "queue_wait_ms": metrics.queue_wait_ms,
        "setup_ms": metrics.setup_ms,
        "backend_ms": metrics.backend_ms,
        "cleanup_ms": metrics.cleanup_ms,
        "total_ms": metrics.total_ms,
        "input_tokens": metrics.input_tokens,
        "output_tokens": metrics.output_tokens,
        "total_tokens": metrics.total_tokens,
        "cpu_time_ms": metrics.cpu_time_ms,
        "peak_rss_mb": metrics.peak_rss_mb,
        "tool_calls": metrics.tool_calls,
        "file_reads": metrics.file_reads,
        "search_calls": metrics.search_calls,
    }
