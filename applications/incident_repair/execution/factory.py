from __future__ import annotations

from typing import Any

from applications.incident_repair.config import ExecutionMode, IncidentRunConfig
from applications.incident_repair.execution.base import ExecutionProvider
from applications.incident_repair.execution.direct import DirectExecutionProvider
from applications.incident_repair.execution.runtime import AgentRuntimeExecutionProvider
from applications.incident_repair.services.replay_service import ReplayExecutionProvider


def create_execution_provider(config: IncidentRunConfig, dependencies: dict[str, Any] | None = None) -> ExecutionProvider:
    dependencies = dependencies or {}
    if dependencies.get("provider") is not None:
        return dependencies["provider"]
    if config.execution_mode == ExecutionMode.DIRECT:
        return DirectExecutionProvider(config=config, dependencies=dependencies)
    if config.execution_mode == ExecutionMode.RUNTIME:
        return AgentRuntimeExecutionProvider(config=config, dependencies=dependencies)
    if config.execution_mode == ExecutionMode.REPLAY:
        return ReplayExecutionProvider(dependencies.get("manifest_path"))
    raise ValueError(f"unsupported mode: {config.execution_mode}")
