import pytest

from aruntime.core.acb import AgentControlBlock
from aruntime.core.models import AgentStatus


def test_acb_rejects_running_to_created():
    acb = AgentControlBlock(agent_name="coder")
    acb.transition_to(AgentStatus.READY, reason="created")
    acb.transition_to(AgentStatus.RUNNING, task_id="t1", reason="dispatch")

    with pytest.raises(ValueError):
        acb.transition_to(AgentStatus.CREATED, reason="invalid")


def test_failed_to_ready_must_pass_recovering():
    acb = AgentControlBlock(agent_name="coder")
    acb.transition_to(AgentStatus.READY)
    acb.transition_to(AgentStatus.RUNNING)
    acb.transition_to(AgentStatus.FAILED, reason="worker.failed")

    with pytest.raises(ValueError):
        acb.transition_to(AgentStatus.READY, reason="invalid_direct_ready")

    acb.transition_to(AgentStatus.RECOVERING, reason="recover.start")
    acb.transition_to(AgentStatus.READY, reason="recover.ready")

    assert acb.status == AgentStatus.READY
    assert [event.to_status for event in acb.timeline][-2:] == [AgentStatus.RECOVERING, AgentStatus.READY]


def test_acb_timeline_records_every_transition():
    acb = AgentControlBlock(agent_name="reviewer")
    acb.transition_to(AgentStatus.READY, reason="created")
    acb.transition_to(AgentStatus.RUNNING, task_id="t2", reason="dispatch")

    assert len(acb.timeline) == 2
    assert acb.timeline[0].reason == "created"
    assert acb.timeline[1].task_id == "t2"


def test_acb_lost_can_recover_or_be_isolated():
    acb = AgentControlBlock(agent_name="coder")
    acb.transition_to(AgentStatus.READY)
    acb.transition_to(AgentStatus.LOST, reason="heartbeat.lost")
    acb.transition_to(AgentStatus.RECOVERING, reason="recover.start")
    acb.transition_to(AgentStatus.READY, reason="recover.ready")

    isolated = AgentControlBlock(agent_name="reviewer", status=AgentStatus.LOST)
    isolated.transition_to(AgentStatus.ISOLATED, reason="heartbeat.isolate")

    assert acb.status == AgentStatus.READY
    assert isolated.status == AgentStatus.ISOLATED
