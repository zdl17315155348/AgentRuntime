from __future__ import annotations

from pydantic import BaseModel, Field


class BenchmarkConfig(BaseModel):
    benchmark_id: str
    task_case: str
    modes: list[str]
    concurrency_levels: list[int]
    warmup_runs: int = 5
    measured_runs: int = 30
    cpu_limit: float
    memory_limit_mb: int
    fault_mode: bool = False
    recovery_context_enabled: bool = True
    codex_model: str | None = None
    deepseek_model: str
    base_commit: str
    prompt_hash: str
    graph_version: str


class RunMetric(BaseModel):
    benchmark_id: str
    run_id: str
    mode: str
    concurrency: int
    measured: bool
    success: bool
    total_ms: float
    queue_wait_ms: float = 0
    backend_ms: float = 0
    peak_rss_mb: float = 0
    error: str = ""


class PairedRun(BaseModel):
    pair_id: str
    direct_run_id: str
    runtime_run_id: str
    comparable: bool
    reason: str = ""
