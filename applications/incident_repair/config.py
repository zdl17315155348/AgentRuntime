from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pydantic import BaseModel


class ExecutionMode(str, Enum):
    DIRECT = "direct"
    RUNTIME = "runtime"
    REPLAY = "replay"


class IncidentRunConfig(BaseModel):
    execution_mode: ExecutionMode
    run_id: str
    thread_id: str
    source_repo: str
    base_commit: str
    max_concurrency: int = 4
    max_repair_rounds: int = 2
    deepseek_model: str = "deepseek-chat"
    codex_model: str | None = None
    task_timeout_s: int = 300
    workflow_timeout_s: int = 900
    fault_mode: bool = False
    fault_target_role: str = "coder"
    fault_trigger: str = "after_first_file_read"
    cpu_limit: float | None = None
    memory_limit_mb: int | None = None
    benchmark_id: str | None = None
    random_seed: int = 42


@dataclass
class GraphRuntimeContext:
    provider: object
    run_config: IncidentRunConfig
    event_bus: object
    integration_service: object | None = None


def default_checkpoint_path() -> Path:
    return Path("run-data/langgraph/checkpoints.sqlite")
