import pytest

from aruntime.backends.registry import BackendRegistry
from aruntime.core.models import AgentBackendConfig, AgentBackendType


def test_registry_creates_backend():
    registry = BackendRegistry()
    registry.register(AgentBackendType.LEGACY_LLM, lambda config, deps: ("ok", config.type))

    assert registry.create(AgentBackendConfig(), {}) == ("ok", AgentBackendType.LEGACY_LLM)


def test_registry_rejects_unknown_backend():
    registry = BackendRegistry()
    with pytest.raises(ValueError):
        registry.create(AgentBackendConfig(type=AgentBackendType.CODEX_CLI), {})
