from __future__ import annotations

from typing import Any, Callable

from aruntime.core.models import AgentBackendConfig, AgentBackendType


class BackendRegistry:
    def __init__(self) -> None:
        self._factories: dict[AgentBackendType, Callable[[AgentBackendConfig, dict[str, Any]], Any]] = {}

    def register(self, backend_type: AgentBackendType, factory: Callable[[AgentBackendConfig, dict[str, Any]], Any]) -> None:
        self._factories[AgentBackendType(backend_type)] = factory

    def create(self, config: AgentBackendConfig, dependencies: dict[str, Any]):
        factory = self._factories.get(config.type)
        if factory is None:
            raise ValueError(f"unsupported backend: {config.type}")
        return factory(config, dependencies)


default_backend_registry = BackendRegistry()
