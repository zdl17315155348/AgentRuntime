from __future__ import annotations

import pytest

from applications.incident_repair.config import ExecutionMode, IncidentRunConfig
from applications.incident_repair.execution.base import AgentExecutionRequest, AgentExecutionResult, ExecutionMetrics
from applications.incident_repair.execution.direct import DirectExecutionProvider
from applications.incident_repair.execution.factory import create_execution_provider
from applications.incident_repair.execution.runtime import RuntimeSystemError


def _config(mode: ExecutionMode = ExecutionMode.DIRECT) -> IncidentRunConfig:
    return IncidentRunConfig(
        execution_mode=mode,
        run_id="run1",
        thread_id="thread1",
        source_repo=".",
        base_commit="HEAD",
        max_concurrency=1,
    )


def _request(backend: str = "deepseek", role: str = "planner") -> AgentExecutionRequest:
    return AgentExecutionRequest(
        run_id="run1",
        thread_id="thread1",
        graph_node=role,
        graph_step=0,
        role=role,
        backend=backend,
        goal="fix auth",
        source_repo=".",
        base_commit="HEAD",
        idempotency_key="idem",
    )


@pytest.mark.anyio
async def test_direct_tester_uses_integrated_commit_worktree(monkeypatch):
    created = {}

    class _WorkspaceManager:
        def create_attempt_workspace(self, source_repo, task_id, attempt_id, base_ref, read_only, root_task_id=None):
            created.update({"source_repo": source_repo, "task_id": task_id, "attempt_id": attempt_id, "base_ref": base_ref, "read_only": read_only, "root_task_id": root_task_id})
            return type("W", (), {"workspace_path": "/tmp/integrated"})()

        def cleanup_workspace(self, workspace, force=False):
            created["cleanup"] = force

    async def fake_pytest(workspace_path, timeout_s, junit_xml="pytest.xml"):
        created["workspace_path"] = workspace_path
        return {"returncode": 0, "passed": 1, "failed": 0, "failed_tests": [], "report_artifact_id": None}

    monkeypatch.setattr("applications.incident_repair.execution.direct.run_pytest_direct", fake_pytest)
    provider = DirectExecutionProvider(_config(), {"workspace_manager": _WorkspaceManager()})
    result = await provider.execute(
        AgentExecutionRequest(
            run_id="run1",
            thread_id="thread1",
            graph_node="tester",
            graph_step=3,
            role="tester",
            backend="direct_tool",
            goal="run pytest",
            task_input={"integrated_commit": "abc123"},
            source_repo=".",
            base_commit="HEAD",
            idempotency_key="idem",
            timeout_s=30,
        )
    )

    assert created["base_ref"] == "abc123"
    assert created["read_only"] is True
    assert created["workspace_path"] == "/tmp/integrated"
    assert result.status == "SUCCESS"


@pytest.mark.anyio
async def test_direct_provider_returns_common_result_shape_for_planner():
    class _DeepSeek:
        async def execute_plan(self, system_prompt, goal, source_repo, available_roles):
            return {
                "version": "1.0",
                "summary": "direct",
                "tasks": [
                    {"local_id": "coder", "role": "coder", "goal": goal, "dependencies": []},
                    {"local_id": "tester", "role": "tester", "goal": "test", "dependencies": ["coder"]},
                    {"local_id": "reviewer", "role": "reviewer", "goal": "review", "dependencies": ["tester"]},
                ],
            }

    provider = DirectExecutionProvider(_config(), {"deepseek": _DeepSeek()})
    result = await provider.execute(_request())

    assert isinstance(result, AgentExecutionResult)
    assert result.status == "SUCCESS"
    assert result.structured_result["tasks"][0]["role"] == "coder"
    assert result.metrics.total_ms >= 0


@pytest.mark.anyio
async def test_direct_codex_provider_uses_pydantic_validation_without_cli_schema():
    captured = {}

    class _WorkspaceManager:
        def create_attempt_workspace(self, source_repo, task_id, attempt_id, base_ref, read_only, root_task_id=None):
            return type("W", (), {"workspace_path": "/tmp/workspace"})()

        def create_patch_artifact(self, workspace, task_id, attempt_id, root_task_id=None):
            return None

    class _Codex:
        async def execute(self, *args, **kwargs):
            captured.update(kwargs)
            return 0, "", "", 123

    provider = DirectExecutionProvider(_config(), {"workspace_manager": _WorkspaceManager(), "codex": _Codex()})
    result = await provider.execute(_request("codex_cli", "coder"))

    assert "output_schema" not in captured or captured["output_schema"] is None
    assert result.status == "SUCCESS"


def test_provider_factory_switches_modes():
    assert create_execution_provider(_config(ExecutionMode.DIRECT)).mode == "direct"
    assert create_execution_provider(_config(ExecutionMode.REPLAY)).mode == "replay"


class _FakeClient:
    def __init__(self):
        self.submitted = None
        self.cancelled = []

    def submit_task(self, agent_name, task_input, **kwargs):
        self.submitted = {"agent_name": agent_name, "task_input": task_input, **kwargs}
        return {"task_id": "t1", "status": "PENDING"}

    def wait_task(self, task_id, timeout_s):
        return {
            "task_id": task_id,
            "status": "SUCCESS",
            "result": {"output": {"returncode": 0, "passed": 1, "failed": 0, "failed_tests": [], "report_artifact_id": None}},
            "attempts": [{"attempt_id": "a1"}],
            "scheduler": {"queue_wait_ms": 3},
        }

    def cancel_task(self, task_id):
        self.cancelled.append(task_id)
        return {"task_id": task_id, "cancelled": True}


@pytest.mark.anyio
async def test_runtime_provider_reuses_client_and_maps_request_fields():
    provider = create_execution_provider(_config(ExecutionMode.RUNTIME), {"client": _FakeClient()})
    result = await provider.execute(_request("direct_tool", "tester"))

    client = provider.client
    assert client.submitted["required_backend"] == "direct_tool"
    assert client.submitted["task_role"] == "tester"
    assert client.submitted["idempotency_key"] == "idem"
    assert client.submitted["task_input"]["graph"]["node"] == "tester"
    assert result.status == "SUCCESS"
    assert result.runtime_task_id == "t1"
    assert result.structured_result["returncode"] == 0
    assert client.submitted["task_input"]["graph_managed"] is True


@pytest.mark.anyio
async def test_runtime_provider_parses_direct_tool_json_output():
    class _DirectToolJsonClient(_FakeClient):
        def wait_task(self, task_id, timeout_s):
            return {
                "task_id": task_id,
                "status": "SUCCESS",
                "result": {"output": '{"returncode": 1, "passed": 0, "failed": 1, "failed_tests": [{"name": "t::fail", "message": "boom"}], "report_artifact_id": null}'},
                "attempts": [{"attempt_id": "a1"}],
                "scheduler": {},
            }

    provider = create_execution_provider(_config(ExecutionMode.RUNTIME), {"client": _DirectToolJsonClient()})
    result = await provider.execute(_request("direct_tool", "tester"))

    assert result.status == "SUCCESS"
    assert result.structured_result["returncode"] == 1
    assert result.structured_result["failed_tests"][0]["name"] == "t::fail"


class _PlannerClient(_FakeClient):
    def wait_task(self, task_id, timeout_s):
        return {
            "task_id": task_id,
            "status": "SUCCESS",
            "result": {
                "output": '{"inspection": {}, "plan": {"version": "1.0", "summary": "p", "tasks": [{"local_id": "c", "role": "coder", "goal": "g", "dependencies": []}]}}'
            },
            "attempts": [{"attempt_id": "a1"}],
            "scheduler": {},
        }


@pytest.mark.anyio
async def test_runtime_provider_returns_planner_plan_without_runtime_dag_materialization():
    provider = create_execution_provider(_config(ExecutionMode.RUNTIME), {"client": _PlannerClient()})
    result = await provider.execute(_request("deepseek", "planner"))

    assert provider.client.submitted["task_input"]["graph_managed"] is True
    assert result.structured_result["tasks"][0]["local_id"] == "c"


@pytest.mark.anyio
async def test_runtime_provider_parses_codex_coder_json_output():
    class _CodexCoderClient(_FakeClient):
        def wait_task(self, task_id, timeout_s):
            return {
                "task_id": task_id,
                "status": "SUCCESS",
                "result": {"output": '{"completed": true, "summary": "fixed", "tests_run": ["pytest"], "remaining_issues": []}'},
                "attempts": [{"attempt_id": "a1"}],
                "scheduler": {},
            }

    provider = create_execution_provider(_config(ExecutionMode.RUNTIME), {"client": _CodexCoderClient()})
    result = await provider.execute(_request("codex_cli", "coder"))

    assert result.structured_result == {
        "completed": True,
        "summary": "fixed",
        "tests_run": ["pytest"],
        "remaining_issues": [],
    }


@pytest.mark.anyio
async def test_runtime_provider_parses_codex_repair_json_output():
    class _CodexRepairClient(_FakeClient):
        def wait_task(self, task_id, timeout_s):
            return {
                "task_id": task_id,
                "status": "SUCCESS",
                "result": {"output": {"completed": True, "summary": "repaired", "tests_run": [], "remaining_issues": ["needs review"]}},
                "attempts": [{"attempt_id": "a1"}],
                "scheduler": {},
            }

    provider = create_execution_provider(_config(ExecutionMode.RUNTIME), {"client": _CodexRepairClient()})
    result = await provider.execute(_request("codex_cli", "repair"))

    assert result.structured_result["completed"] is True
    assert result.structured_result["remaining_issues"] == ["needs review"]


@pytest.mark.anyio
async def test_runtime_provider_parses_reviewer_approved_from_structured_output_not_exit_code():
    class _ReviewerClient(_FakeClient):
        def wait_task(self, task_id, timeout_s):
            return {
                "task_id": task_id,
                "status": "SUCCESS",
                "result": {
                    "output": '{"approved": false, "requirements_covered": ["tests"], "issues": ["missing edge"], "summary": "reject", "artifact_id": "review1"}',
                    "exit_code": 0,
                },
                "attempts": [{"attempt_id": "a1"}],
                "scheduler": {},
            }

    provider = create_execution_provider(_config(ExecutionMode.RUNTIME), {"client": _ReviewerClient()})
    result = await provider.execute(_request("codex_cli", "reviewer"))

    assert result.status == "SUCCESS"
    assert result.structured_result["approved"] is False
    assert result.structured_result["issues"] == ["missing edge"]


@pytest.mark.anyio
async def test_runtime_provider_fails_invalid_codex_json():
    class _InvalidJsonClient(_FakeClient):
        def wait_task(self, task_id, timeout_s):
            return {
                "task_id": task_id,
                "status": "SUCCESS",
                "result": {"output": "{not-json"},
                "attempts": [{"attempt_id": "a1"}],
                "scheduler": {},
            }

    provider = create_execution_provider(_config(ExecutionMode.RUNTIME), {"client": _InvalidJsonClient()})
    with pytest.raises(RuntimeSystemError, match="invalid structured output"):
        await provider.execute(_request("codex_cli", "coder"))


@pytest.mark.anyio
async def test_runtime_provider_fails_empty_codex_output():
    class _EmptyOutputClient(_FakeClient):
        def wait_task(self, task_id, timeout_s):
            return {
                "task_id": task_id,
                "status": "SUCCESS",
                "result": {"output": ""},
                "attempts": [{"attempt_id": "a1"}],
                "scheduler": {},
            }

    provider = create_execution_provider(_config(ExecutionMode.RUNTIME), {"client": _EmptyOutputClient()})
    with pytest.raises(RuntimeSystemError, match="empty structured output"):
        await provider.execute(_request("codex_cli", "coder"))


@pytest.mark.anyio
async def test_runtime_provider_keeps_direct_tool_business_result_without_forcing_success():
    class _FailingClient(_FakeClient):
        def wait_task(self, task_id, timeout_s):
            return {
                "task_id": task_id,
                "status": "SUCCESS",
                "result": {"output": {"returncode": 1, "passed": 0, "failed": 1, "failed_tests": [{"name": "t::fail", "message": "boom"}], "report_artifact_id": None}},
                "attempts": [{"attempt_id": "a1"}],
                "scheduler": {"queue_wait_ms": 3},
            }

    provider = create_execution_provider(_config(ExecutionMode.RUNTIME), {"client": _FailingClient()})
    result = await provider.execute(_request("direct_tool", "tester"))

    assert result.status == "SUCCESS"
    assert result.structured_result["returncode"] == 1


@pytest.mark.anyio
async def test_runtime_provider_marks_worker_crash_as_failed_system_state():
    class _CrashClient(_FakeClient):
        def wait_task(self, task_id, timeout_s):
            return {
                "task_id": task_id,
                "status": "FAILED",
                "error": "worker.lost",
                "result": {"output": ""},
                "attempts": [{"attempt_id": "a1"}],
                "scheduler": {},
            }

    provider = create_execution_provider(_config(ExecutionMode.RUNTIME), {"client": _CrashClient()})
    result = await provider.execute(_request("direct_tool", "tester"))

    assert result.status == "FAILED"
    assert result.error_message == "worker.lost"
    assert result.structured_result == {}


@pytest.mark.anyio
async def test_runtime_provider_marks_pytest_timeout_as_timeout_system_state():
    class _TimeoutClient(_FakeClient):
        def wait_task(self, task_id, timeout_s):
            return {
                "task_id": task_id,
                "status": "TIMEOUT",
                "error": "task timeout",
                "result": {"output": ""},
                "attempts": [{"attempt_id": "a1"}],
                "scheduler": {},
            }

    provider = create_execution_provider(_config(ExecutionMode.RUNTIME), {"client": _TimeoutClient()})
    result = await provider.execute(_request("direct_tool", "tester"))

    assert result.status == "TIMEOUT"
    assert result.error_message == "task timeout"
    assert result.structured_result == {}


@pytest.mark.anyio
async def test_runtime_provider_reports_missing_tool_as_system_error():
    class _MissingToolClient(_FakeClient):
        def wait_task(self, task_id, timeout_s):
            return {
                "task_id": task_id,
                "status": "FAILED",
                "error": "tool 'pytest' is not allowed for agent 'tester'",
                "result": {"output": ""},
                "attempts": [{"attempt_id": "a1"}],
                "scheduler": {},
            }

    provider = create_execution_provider(_config(ExecutionMode.RUNTIME), {"client": _MissingToolClient()})
    result = await provider.execute(_request("direct_tool", "tester"))

    assert result.status == "FAILED"
    assert "tool 'pytest' is not allowed" in (result.error_message or "")
    assert result.structured_result == {}
