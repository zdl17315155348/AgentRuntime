import pytest

from aruntime.core.models import AgentBackendConfig, AgentBackendType, AgentCapability, TaskAttempt, AgentSpec, SideEffectLevel, TaskSpec, TaskStatus, WorkspaceSpec


def test_agent_spec_has_runtime_capability_and_quotas():
    agent = AgentSpec(
        agent_name="coder",
        role="code",
        capability=AgentCapability(can_code=True, languages=["python"], cost_level=2, reliability_score=0.9),
        restart_budget=2,
        fault_domain="fd-a",
        token_quota=4096,
    )

    assert agent.capability.can_code is True
    assert agent.capability.languages == ["python"]
    assert agent.restart_budget == 2
    assert agent.fault_domain == "fd-a"
    assert agent.token_quota == 4096
    assert agent.backend.type == AgentBackendType.LEGACY_LLM


def test_task_spec_declares_capability_dependencies_and_side_effects():
    task = TaskSpec(
        task_input={"request": "edit"},
        required_capability={"can_code": True, "language": "python"},
        dependencies=["design"],
        children=["test"],
        idempotency_key="edit-1",
        side_effect_level=SideEffectLevel.FILE_WRITE,
    )

    assert task.agent_name is None
    assert task.required_capability["can_code"] is True
    assert task.dependencies == ["design"]
    assert task.children == ["test"]
    assert task.side_effect_level == SideEffectLevel.FILE_WRITE
    assert task.root_task_id == task.task_id


def test_backend_config_rejects_danger_full_access_for_codex():
    with pytest.raises(ValueError):
        AgentBackendConfig(type=AgentBackendType.CODEX_CLI, sandbox="danger-full-access")


def test_task_attempt_serializes_backend_workspace_fields():
    attempt = TaskAttempt(
        attempt_id="t:attempt:1",
        agent_name="coder",
        backend_type="codex_cli",
        workspace_path="/tmp/ws",
        base_commit="abc",
    )

    restored = TaskAttempt(**attempt.model_dump(mode="json"))

    assert restored.backend_type == "codex_cli"
    assert restored.workspace_path == "/tmp/ws"


def test_task_fsm_rejects_illegal_running_to_created():
    task = TaskSpec(agent_name="a", task_input={})
    task.transition_to(TaskStatus.READY, "enqueue")
    task.transition_to(TaskStatus.RUNNING, "dispatch")

    try:
        task.transition_to(TaskStatus.PENDING, "preempt")
    except ValueError:
        raise AssertionError("RUNNING -> PENDING should remain legal for retry/preemption")

    task.transition_to(TaskStatus.READY, "retry_ready")
    assert task.status == TaskStatus.READY
