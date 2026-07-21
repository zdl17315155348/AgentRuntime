import json
from pathlib import Path

import pytest

from aruntime.backends.base import BackendExecutionResult
from aruntime.core.models import AgentBackendConfig, AgentBackendType, AgentCapability, AgentSpec
from aruntime.worker.agent_worker import _run_exec_task


class _Backend:
    def __init__(self, backend_type: AgentBackendType, events: list[dict], status: str = "SUCCESS", output: str | None = None, backend_pid: int | None = 4321):
        self.backend_type = backend_type
        self.events = events
        self.status = status
        self.output = output
        self.backend_pid = backend_pid

    async def prepare(self, request):
        return None

    async def execute(self, request, emit_event):
        event = {"name": "backend.started", "backend_type": self.backend_type.value, "backend_pid": self.backend_pid}
        self.events.append(event)
        await emit_event(event)
        return BackendExecutionResult(
            status=self.status,
            output=self.output or json.dumps({"backend": self.backend_type.value}),
            backend_type=self.backend_type.value,
            backend_pid=self.backend_pid,
        )

    async def cleanup(self, request):
        return None

    async def cancel(self, attempt_id):
        return None


class _Registry:
    def __init__(self):
        self.created: list[AgentBackendType] = []
        self.events: list[dict] = []

    def create(self, config, dependencies):
        self.created.append(config.type)
        return _Backend(config.type, self.events)


class _Gateway:
    backend = "real"


class _Executor:
    pass


async def _run_worker(agent_spec: AgentSpec, tmp_path: Path) -> tuple[_Registry, list[dict]]:
    registry = _Registry()
    sent: list[dict] = []

    async def send_json(payload: dict) -> None:
        sent.append(payload)

    await _run_exec_task(
        {
            "task_id": "task1",
            "attempt_id": "attempt1",
            "task_input": {"request": "run"},
            "workspace": {"source_repo": str(tmp_path), "workspace_path": str(tmp_path)},
            "timeout_s": 30,
        },
        send_json,
        _Gateway(),
        _Executor(),
        agent_spec,
        registry,
    )
    return registry, sent


@pytest.mark.anyio
async def test_worker_dispatches_heterogeneous_backends(tmp_path):
    cases = [
        ("architect", AgentBackendType.NATIVE_PLANNER),
        ("coder_a", AgentBackendType.CODEX_CLI),
        ("tester", AgentBackendType.DIRECT_TOOL),
    ]

    for agent_name, backend_type in cases:
        registry, sent = await _run_worker(
            AgentSpec(agent_name=agent_name, role=agent_name, backend=AgentBackendConfig(type=backend_type)),
            tmp_path,
        )

        assert registry.created == [backend_type]
        assert any(event["type"] == "backend_started" and event["backend_type"] == backend_type.value for event in sent)
        result = next(event for event in sent if event["type"] == "task_result")
        assert result["backend_type"] == backend_type.value


@pytest.mark.anyio
async def test_worker_preserves_reviewer_codex_read_only_sandbox(tmp_path):
    registry, sent = await _run_worker(
        AgentSpec(
            agent_name="reviewer",
            role="reviewer",
            capability=AgentCapability(can_review=True),
            backend=AgentBackendConfig(type=AgentBackendType.CODEX_CLI, sandbox="read-only"),
        ),
        tmp_path,
    )

    assert registry.created == [AgentBackendType.CODEX_CLI]
    assert sent[-1]["status"] == "SUCCESS"


@pytest.mark.anyio
async def test_worker_coder_does_not_fallback_to_legacy_llm(tmp_path):
    registry, sent = await _run_worker(
        AgentSpec(
            agent_name="coder_a",
            role="coder",
            capability=AgentCapability(can_code=True),
            backend=AgentBackendConfig(type=AgentBackendType.CODEX_CLI, sandbox="workspace-write"),
        ),
        tmp_path,
    )

    assert registry.created == [AgentBackendType.CODEX_CLI]
    assert all(event.get("backend_type") != AgentBackendType.LEGACY_LLM.value for event in sent)
