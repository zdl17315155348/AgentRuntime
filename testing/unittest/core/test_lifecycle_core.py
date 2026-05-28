"""
单元测试：Agent 生命周期状态机
直接测试 lifecycle.py 中的状态转换逻辑
"""

import pytest
from aruntime.core.models import AgentSpec, AgentStatus
from aruntime.core.lifecycle import transition_to, can_transition_to, InvalidTransitionError


def _make_agent(status=AgentStatus.CREATED):
    """创建一个指定状态的测试 Agent"""
    agent = AgentSpec(agent_name="test_agent", role="测试员")
    agent.status = status
    return agent

class TestLifecycleBasic:
    """测试基本状态转换"""

    def test_initial_status(self):
        """Agent 创建后初始状态为 CREATED"""
        agent = AgentSpec(agent_name="test", role="test")
        assert agent.status == AgentStatus.CREATED

    def test_created_to_ready(self):
        """CREATED → READY 合法"""
        agent = _make_agent(AgentStatus.CREATED)
        transition_to(agent, AgentStatus.READY)
        assert agent.status == AgentStatus.READY

    def test_ready_to_running(self):
        """READY → RUNNING 合法"""
        agent = _make_agent(AgentStatus.READY)
        transition_to(agent, AgentStatus.RUNNING)
        assert agent.status == AgentStatus.RUNNING

    def test_running_to_completed(self):
        """RUNNING → COMPLETED 合法"""
        agent = _make_agent(AgentStatus.RUNNING)
        transition_to(agent, AgentStatus.COMPLETED)
        assert agent.status == AgentStatus.COMPLETED

    def test_running_to_failed(self):
        """RUNNING → FAILED 合法"""
        agent = _make_agent(AgentStatus.RUNNING)
        transition_to(agent, AgentStatus.FAILED)
        assert agent.status == AgentStatus.FAILED

    def test_failed_to_ready(self):
        """FAILED → READY 合法（失败后可重试）"""
        agent = _make_agent(AgentStatus.FAILED)
        transition_to(agent, AgentStatus.READY)
        assert agent.status == AgentStatus.READY

    def test_running_to_waiting(self):
        """RUNNING → WAITING 合法"""
        agent = _make_agent(AgentStatus.RUNNING)
        transition_to(agent, AgentStatus.WAITING)
        assert agent.status == AgentStatus.WAITING

    def test_waiting_to_ready(self):
        """WAITING → READY 合法（等待结束后重新就绪）"""
        agent = _make_agent(AgentStatus.WAITING)
        transition_to(agent, AgentStatus.READY)
        assert agent.status == AgentStatus.READY

class TestLifecycleInvalidTransitions:
    """测试非法状态转换"""
    def test_created_to_running_not_allowed(self):
        """CREATED → RUNNING 非法（必须先 READY）"""
        agent = _make_agent(AgentStatus.CREATED)
        with pytest.raises(InvalidTransitionError):
            transition_to(agent, AgentStatus.RUNNING)

    def test_created_to_completed_not_allowed(self):
        """CREATED → COMPLETED 非法"""
        agent = _make_agent(AgentStatus.CREATED)
        with pytest.raises(InvalidTransitionError):
            transition_to(agent, AgentStatus.COMPLETED)

    def test_completed_to_ready_not_allowed(self):
        """COMPLETED → READY 非法（终态不可回退）"""
        agent = _make_agent(AgentStatus.COMPLETED)
        with pytest.raises(InvalidTransitionError):
            transition_to(agent, AgentStatus.READY)

    def test_killed_to_ready_not_allowed(self):
        """KILLED → READY 非法（终态不可回退）"""
        agent = _make_agent(AgentStatus.KILLED)
        with pytest.raises(InvalidTransitionError):
            transition_to(agent, AgentStatus.READY)

    def test_running_to_created_not_allowed(self):
        """RUNNING → CREATED 非法（不能回退到初始状态）"""
        agent = _make_agent(AgentStatus.RUNNING)
        with pytest.raises(InvalidTransitionError):
            transition_to(agent, AgentStatus.CREATED)

class TestLifecycleCanTransition:
    """测试 can_transition_to 辅助函数"""

    def test_can_transition_legal(self):
        """合法转换返回 True"""
        agent = _make_agent(AgentStatus.CREATED)
        assert can_transition_to(agent, AgentStatus.READY) is True
        assert can_transition_to(agent, AgentStatus.KILLED) is True

    def test_can_transition_illegal(self):
        """非法转换返回 False"""
        agent = _make_agent(AgentStatus.CREATED)
        assert can_transition_to(agent, AgentStatus.RUNNING) is False
        assert can_transition_to(agent, AgentStatus.COMPLETED) is False

    def test_completed_cannot_transition(self):
        """终态 COMPLETED 不能转换到任何状态"""
        agent = _make_agent(AgentStatus.COMPLETED)
        for status in AgentStatus:
            assert can_transition_to(agent, status) is False

    def test_killed_cannot_transition(self):
        """终态 KILLED 不能转换到任何状态"""
        agent = _make_agent(AgentStatus.KILLED)
        for status in AgentStatus:
            assert can_transition_to(agent, status) is False
