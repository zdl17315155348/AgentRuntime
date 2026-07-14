from aruntime.core.models import AgentCapability, AgentSpec, TaskSpec, TaskStatus
from aruntime.scheduler.kernel import KernelScheduler


def test_planner_task_dispatches_to_can_plan_agent():
    agents = [
        AgentSpec(agent_name="coder", role="code", capability=AgentCapability(can_code=True)),
        AgentSpec(agent_name="architect", role="plan", capability=AgentCapability(can_plan=True)),
    ]
    scheduler = KernelScheduler(policy="capability_aware", agent_provider=lambda: agents)
    task = TaskSpec(task_input={"request": "plan"}, required_capability={"can_plan": True})

    scheduler.enqueue(task)
    got = scheduler.dequeue()

    assert got is task
    assert task.agent_name == "architect"
    assert task.status == TaskStatus.RUNNING
    assert "capability_match" in task.scheduler_decision_reason


def test_python_code_task_prefers_python_agent():
    agents = [
        AgentSpec(agent_name="js", role="code", capability=AgentCapability(can_code=True, languages=["javascript"])),
        AgentSpec(agent_name="py", role="code", capability=AgentCapability(can_code=True, languages=["python"])),
    ]
    scheduler = KernelScheduler(policy="capability_aware", agent_provider=lambda: agents)
    task = TaskSpec(task_input={}, required_capability={"can_code": True, "language": "python"})

    scheduler.enqueue(task)

    assert scheduler.dequeue().agent_name == "py"


def test_reliability_aware_selects_more_reliable_agent():
    agents = [
        AgentSpec(agent_name="codex", role="code", capability=AgentCapability(can_code=True, languages=["python"], reliability_score=0.2)),
        AgentSpec(agent_name="cursor", role="code", capability=AgentCapability(can_code=True, languages=["python"], reliability_score=0.9)),
    ]
    scheduler = KernelScheduler(policy="reliability_aware", agent_provider=lambda: agents)
    task = TaskSpec(task_input={}, required_capability={"can_code": True, "language": "python"})

    scheduler.enqueue(task)

    assert scheduler.dequeue().agent_name == "cursor"


def test_matching_task_blocks_when_resource_unavailable():
    agents = [AgentSpec(agent_name="coder", role="code", capability=AgentCapability(can_code=True))]
    scheduler = KernelScheduler(
        policy="capability_aware",
        agent_provider=lambda: agents,
        resource_checker=lambda task: (False, "llm_concurrency_quota"),
    )
    task = TaskSpec(task_input={}, required_capability={"can_code": True})

    scheduler.enqueue(task)

    assert scheduler.dequeue() is None
    assert task.status == TaskStatus.BLOCKED
    assert task.resource_block_reason == "llm_concurrency_quota"
