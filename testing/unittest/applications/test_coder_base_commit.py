from __future__ import annotations

from applications.incident_repair.config import ExecutionMode, GraphRuntimeContext, IncidentRunConfig
from applications.incident_repair.execution.base import AgentExecutionRequest, AgentExecutionResult, ExecutionMetrics, ExecutionProvider
from applications.incident_repair.nodes.coder import coder_node


class _Provider(ExecutionProvider):
    def __init__(self, status: str = "SUCCESS"):
        self.request: AgentExecutionRequest | None = None
        self.status = status

    @property
    def mode(self):
        return "direct"

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        self.request = request
        if self.status != "SUCCESS":
            return AgentExecutionResult(
                status="TIMEOUT",
                error_message="codex timeout",
                metrics=ExecutionMetrics(submit_started_at=0, execution_started_at=0, execution_finished_at=0),
            )
        return AgentExecutionResult(
            status="SUCCESS",
            patch_ref={
                "task_local_id": request.task_input["local_id"],
                "artifact_id": "patch",
                "patch_path": "/tmp/patch.diff",
                "sha256": "sha",
                "changed_files": ["app.py"],
            },
            metrics=ExecutionMetrics(submit_started_at=0, execution_started_at=0, execution_finished_at=0),
        )

    async def cancel_run(self, run_id: str) -> None:
        return None

    async def inject_fault(self, run_id: str, target: dict):
        return {}

    async def get_execution_snapshot(self, run_id: str):
        return {}


def _context(provider: _Provider) -> GraphRuntimeContext:
    return GraphRuntimeContext(
        provider=provider,
        run_config=IncidentRunConfig(
            execution_mode=ExecutionMode.DIRECT,
            run_id="run",
            thread_id="thread",
            source_repo="/repo",
            base_commit="base0",
        ),
        event_bus=None,
    )


async def test_coder_uses_latest_integrated_commit(anyio_backend):
    provider = _Provider()

    await coder_node(
        {
            "run_id": "run",
            "thread_id": "thread",
            "source_repo": "/repo",
            "base_commit": "base0",
            "integrated_commit": "base1",
            "coder_step": 2,
            "active_coder_task": {"local_id": "b", "role": "coder", "goal": "fix", "dependencies": ["a"]},
        },
        _context(provider),
    )

    assert provider.request is not None
    assert provider.request.base_commit == "base1"
    assert provider.request.graph_step == 2
    assert provider.request.task_input == {
        "local_id": "b",
        "dependencies": ["a"],
        "base_commit": "base1",
        "coder_step": 2,
    }


async def test_coder_idempotency_key_includes_execution_base_commit(anyio_backend):
    first = _Provider()
    second = _Provider()
    state = {
        "run_id": "run",
        "thread_id": "thread",
        "source_repo": "/repo",
        "base_commit": "base0",
        "coder_step": 1,
        "active_coder_task": {"local_id": "a", "role": "coder", "goal": "fix", "dependencies": []},
    }

    await coder_node({**state, "integrated_commit": None}, _context(first))
    await coder_node({**state, "integrated_commit": "base1"}, _context(second))

    assert first.request is not None
    assert second.request is not None
    assert first.request.idempotency_key != second.request.idempotency_key


async def test_coder_failure_returns_failed_state_with_execution_record(anyio_backend):
    provider = _Provider(status="TIMEOUT")

    update = await coder_node(
        {
            "run_id": "run",
            "thread_id": "thread",
            "source_repo": "/repo",
            "base_commit": "base0",
            "integrated_commit": None,
            "coder_step": 1,
            "active_coder_task": {"local_id": "a", "role": "coder", "goal": "fix", "dependencies": []},
        },
        _context(provider),
    )

    assert update["workflow_status"] == "FAILED"
    assert update["error"] == "codex timeout"
    assert update["execution_records"][0]["role"] == "coder"
