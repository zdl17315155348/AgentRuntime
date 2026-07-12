from aruntime.core.acb import AgentControlBlock
from aruntime.core.lifecycle import transition_to
from aruntime.core.models import AgentSpec, AgentStatus


def test_acb_from_agent_spec_captures_runtime_fields():
    agent = AgentSpec(
        agent_name="planner",
        role="规划者",
        memory_max_bytes=1024,
        memory_high_bytes=512,
        cpu_max="50000 100000",
        pids_max=16,
        llm_max_concurrent=2,
    )

    acb = AgentControlBlock.from_agent_spec(agent)

    assert acb.agent_name == "planner"
    assert acb.status == AgentStatus.CREATED
    assert acb.resource_quota.memory_max_bytes == 1024
    assert acb.resource_quota.memory_high_bytes == 512
    assert acb.resource_quota.cpu_max == "50000 100000"
    assert acb.resource_quota.pids_max == 16
    assert acb.resource_quota.llm_max_concurrent == 2
    assert acb.fault_domain == "planner"
    assert acb.trace_id.startswith("trace_")


def test_acb_transition_is_recorded_in_timeline():
    acb = AgentControlBlock(agent_name="coder")

    transition_to(acb, AgentStatus.READY, reason="created")
    transition_to(acb, AgentStatus.RUNNING, task_id="task-1", reason="dispatch")

    assert acb.status == AgentStatus.RUNNING
    assert len(acb.timeline) == 2
    first = acb.timeline[0].to_dict()
    second = acb.timeline[1].to_dict()
    assert first["from_status"] == "CREATED"
    assert first["to_status"] == "READY"
    assert first["reason"] == "created"
    assert second["task_id"] == "task-1"
    assert second["to_status"] == "RUNNING"


def test_acb_to_dict_contains_observable_runtime_state():
    acb = AgentControlBlock(agent_name="reviewer")
    acb.set_current_task("task-2")
    acb.set_context("ctx-1")
    transition_to(acb, AgentStatus.READY)

    data = acb.to_dict()

    assert data["agent_name"] == "reviewer"
    assert data["status"] == "READY"
    assert data["current_task_id"] == "task-2"
    assert data["context_handle"] == {"context_id": "ctx-1"}
    assert "resource_quota" in data
    assert "fault_domain" in data
    assert "trace_id" in data
    assert len(data["timeline"]) == 1
