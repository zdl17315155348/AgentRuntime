"""
资源感知调度器单元测试
"""

import pytest
from unittest.mock import patch, MagicMock
from aruntime.core.models import TaskSpec, AgentSpec, TaskStatus, AgentStatus
from aruntime.scheduler.fifo import FIFOScheduler
from aruntime.scheduler.dag import DAGScheduler
from aruntime.scheduler.resource_aware import ResourceAwareScheduler
from aruntime.resource.monitor import ResourceMonitor


class TestResourceAwareWithFIFO:
    """ResourceAwareScheduler 包装 FIFOScheduler 的测试"""

    @patch.object(ResourceMonitor, 'has_enough', return_value=True)
    @patch.object(ResourceMonitor, '_check_system_cpu', return_value=True)
    @patch.object(ResourceMonitor, '_check_system_memory', return_value=True)
    @patch.object(ResourceMonitor, '_check_llm_global', return_value=True)
    def test_dequeue_when_resources_sufficient(self, *_):
        """资源充足时正常出队"""
        monitor = ResourceMonitor()
        agents = {
            "agent1": AgentSpec(agent_name="agent1", role="coder", status=AgentStatus.READY),
        }
        inner = FIFOScheduler()
        scheduler = ResourceAwareScheduler(inner, monitor, agents)

        task = TaskSpec(task_id="t1", agent_name="agent1", task_input={"msg": "hello"})
        scheduler.enqueue(task)

        result = scheduler.dequeue()
        assert result is not None
        assert result.task_id == "t1"
        assert result.status == TaskStatus.RUNNING

    @patch.object(ResourceMonitor, 'has_enough', return_value=False)
    @patch.object(ResourceMonitor, '_check_system_cpu', return_value=True)
    @patch.object(ResourceMonitor, '_check_system_memory', return_value=True)
    @patch.object(ResourceMonitor, '_check_llm_global', return_value=True)
    def test_dequeue_when_resources_insufficient(self, *_):
        """资源不足时不从队列取出任务"""
        monitor = ResourceMonitor()
        agents = {
            "agent1": AgentSpec(agent_name="agent1", role="coder", status=AgentStatus.READY),
        }
        inner = FIFOScheduler()
        scheduler = ResourceAwareScheduler(inner, monitor, agents)

        task = TaskSpec(task_id="t1", agent_name="agent1", task_input={"msg": "hello"})
        scheduler.enqueue(task)

        result = scheduler.dequeue()
        assert result is None
        assert scheduler.pending_count == 1  # 任务还在队列里

    def test_acquire_llm_success(self):
        """LLM 资源申请成功"""
        monitor = ResourceMonitor(llm_max_concurrent=3)
        assert monitor.acquire_llm("agent1", llm_max_concurrent=2)
        assert "agent1" in monitor._active_llm_agents

    def test_acquire_llm_exceed_global(self):
        """超过全局 LLM 并发上限时申请失败"""
        monitor = ResourceMonitor(llm_max_concurrent=1)
        assert monitor.acquire_llm("agent1")
        assert not monitor.acquire_llm("agent2")

    def test_acquire_llm_exceed_per_agent(self):
        """超过单 Agent LLM 并发上限时申请失败"""
        monitor = ResourceMonitor(llm_max_concurrent=5)
        assert monitor.acquire_llm("agent1", llm_max_concurrent=1)
        assert not monitor.acquire_llm("agent1", llm_max_concurrent=1)

    def test_release_llm(self):
        """LLM 资源释放后其他 Agent 可以申请"""
        monitor = ResourceMonitor(llm_max_concurrent=1)
        assert monitor.acquire_llm("agent1")
        monitor.release_llm("agent1")
        assert len(monitor._active_llm_agents) == 0
        assert monitor.acquire_llm("agent2")

    def test_release_llm_decrements_count(self):
        """同一 Agent 多次申请后释放计数正确"""
        monitor = ResourceMonitor(llm_max_concurrent=5)
        assert monitor.acquire_llm("agent1", llm_max_concurrent=3)
        assert monitor.acquire_llm("agent1", llm_max_concurrent=3)
        assert monitor._agent_llm_counts["agent1"] == 2
        monitor.release_llm("agent1")
        assert monitor._agent_llm_counts["agent1"] == 1
        monitor.release_llm("agent1")
        assert "agent1" not in monitor._agent_llm_counts

    def test_delegate_enqueue_complete_fail(self):
        """enqueue / complete_task / fail_task 正确委托给 inner"""
        monitor = ResourceMonitor()
        agents = {"agent1": AgentSpec(agent_name="agent1", role="coder", status=AgentStatus.READY)}
        inner = FIFOScheduler()
        scheduler = ResourceAwareScheduler(inner, monitor, agents)

        task = TaskSpec(task_id="t1", agent_name="agent1", task_input={})
        scheduler.enqueue(task)
        assert scheduler.pending_count == 1

        # FIFOScheduler 的 complete_task/fail_task 是 no-op，但委托应无异常
        scheduler.complete_task("t1")
        scheduler.fail_task("t1")
        assert scheduler.pending_count == 1  # FIFO no-op 不清队列

    def test_get_snapshot(self):
        """资源快照包含基本字段"""
        monitor = ResourceMonitor()
        snap = monitor.get_snapshot()
        assert "cpu_percent" in snap
        assert "mem_percent" in snap
        assert "mem_available_mb" in snap
        assert "llm_active_agents" in snap
        assert "llm_total_concurrent" in snap
        assert "llm_max_concurrent" in snap


class TestResourceAwareWithDAG:
    """ResourceAwareScheduler 包装 DAGScheduler 的测试"""

    @patch.object(ResourceMonitor, 'has_enough', return_value=True)
    @patch.object(ResourceMonitor, '_check_system_cpu', return_value=True)
    @patch.object(ResourceMonitor, '_check_system_memory', return_value=True)
    @patch.object(ResourceMonitor, '_check_llm_global', return_value=True)
    def test_dag_dependency_respected(self, *_):
        """资源感知不破坏 DAG 依赖关系"""
        monitor = ResourceMonitor()
        agents = {
            "agent1": AgentSpec(agent_name="agent1", role="planner", status=AgentStatus.READY),
            "agent2": AgentSpec(agent_name="agent2", role="coder", status=AgentStatus.READY),
        }
        inner = DAGScheduler()
        scheduler = ResourceAwareScheduler(inner, monitor, agents)

        task1 = TaskSpec(task_id="t1", agent_name="agent1", task_input={})
        task2 = TaskSpec(task_id="t2", agent_name="agent2", task_input={}, dependencies=["t1"])

        scheduler.enqueue(task1)
        scheduler.enqueue(task2)

        # 资源充足时应先出 task1
        result = scheduler.dequeue()
        assert result is not None
        assert result.task_id == "t1"

        # task2 依赖 task1，还不可出队
        result = scheduler.dequeue()
        assert result is None

        scheduler.complete_task("t1")

        # 现在 task2 依赖已满足
        result = scheduler.dequeue()
        assert result is not None
        assert result.task_id == "t2"

    @patch.object(ResourceMonitor, 'has_enough', return_value=True)
    @patch.object(ResourceMonitor, '_check_system_cpu', return_value=True)
    @patch.object(ResourceMonitor, '_check_system_memory', return_value=True)
    @patch.object(ResourceMonitor, '_check_llm_global', return_value=True)
    def test_agent_not_in_agents_dict(self, *_):
        """Agent 不在 agents_dict 中时跳过"""
        monitor = ResourceMonitor()
        agents = {}  # 空 agents
        inner = FIFOScheduler()
        scheduler = ResourceAwareScheduler(inner, monitor, agents)

        task = TaskSpec(task_id="t1", agent_name="unknown", task_input={})
        scheduler.enqueue(task)

        result = scheduler.dequeue()
        assert result is None

    @patch.object(ResourceMonitor, 'has_enough', side_effect=[False, True])
    @patch.object(ResourceMonitor, '_check_system_cpu', return_value=True)
    @patch.object(ResourceMonitor, '_check_system_memory', return_value=True)
    @patch.object(ResourceMonitor, '_check_llm_global', return_value=True)
    def test_skip_resource_insufficient_task(self, *_):
        """第一个任务资源不足时跳过，取第二个"""
        monitor = ResourceMonitor()
        agents = {
            "agent1": AgentSpec(agent_name="agent1", role="coder", status=AgentStatus.READY),
            "agent2": AgentSpec(agent_name="agent2", role="tester", status=AgentStatus.READY),
        }
        inner = FIFOScheduler()
        scheduler = ResourceAwareScheduler(inner, monitor, agents)

        task1 = TaskSpec(task_id="t1", agent_name="agent1", task_input={})
        task2 = TaskSpec(task_id="t2", agent_name="agent2", task_input={})
        scheduler.enqueue(task1)
        scheduler.enqueue(task2)

        # has_enough 第 1 次返回 False, 第 2 次返回 True → 取 task2
        result = scheduler.dequeue()
        assert result is not None
        assert result.task_id == "t2"
        assert scheduler.pending_count == 1  # task1 还在
