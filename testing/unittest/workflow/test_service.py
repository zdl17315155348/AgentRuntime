import json

from aruntime.core.models import AgentBackendType, AgentCapability, AgentSpec, TaskSpec, TaskStatus, WorkspaceSpec
from aruntime.workflow.service import WorkflowService
from aruntime.workspace.manager import WorkspaceManager


def test_workflow_materializes_planner_output(tmp_path):
    tasks = {}
    enqueued = []
    agents = {
        "coder": AgentSpec(agent_name="coder", role="Coder", capability=AgentCapability(can_code=True)),
        "tester": AgentSpec(agent_name="tester", role="Tester", capability=AgentCapability(can_test=True, tools=["run_pytest"])),
        "reviewer": AgentSpec(agent_name="reviewer", role="Reviewer", capability=AgentCapability(can_review=True)),
    }
    service = WorkflowService(
        WorkspaceManager(str(tmp_path / "workspaces")),
        tasks,
        lambda: agents,
        lambda task: enqueued.append(task.task_id),
        lambda task, name, detail=None: None,
        lambda task: None,
    )
    planner = TaskSpec(
        task_id="root",
        agent_name="architect",
        task_input={},
        required_backend=AgentBackendType.NATIVE_PLANNER,
        workspace=WorkspaceSpec(source_repo=str(tmp_path)),
    )
    planner.transition_to(TaskStatus.READY, "x")
    planner.transition_to(TaskStatus.RUNNING, "x")
    planner.transition_to(TaskStatus.SUCCESS, "x")
    planner.result = {
        "output": json.dumps(
            {
                "inspection": {},
                "plan": {
                    "version": "1.0",
                    "summary": "x",
                    "tasks": [
                        {"local_id": "fix", "role": "coder", "goal": "fix"},
                        {"local_id": "test", "role": "tester", "goal": "test", "dependencies": ["fix"]},
                        {"local_id": "review", "role": "reviewer", "goal": "review", "dependencies": ["test"]},
                    ],
                },
            }
        )
    }

    created = service.handle_task_success(planner)

    assert len(created) == 3
    assert created[0].agent_name == "coder"
    assert created[1].required_backend == AgentBackendType.DIRECT_TOOL
    assert created[1].task_input["__tool"]["name"] == "run_pytest"
    assert enqueued == [task.task_id for task in created]
