from __future__ import annotations

from aruntime.core.models import AgentBackendType, TaskSpec, TaskStatus
from aruntime.workflow.service import WorkflowService
from aruntime.workspace.manager import WorkspaceManager


def test_graph_managed_native_planner_does_not_materialize_runtime_children():
    task = TaskSpec(
        agent_name="architect",
        task_input={"graph_managed": True},
        required_backend=AgentBackendType.NATIVE_PLANNER,
        status=TaskStatus.SUCCESS,
        result={"output": '{"plan": {"version": "1.0", "summary": "x", "tasks": []}}'},
    )
    tasks = {task.task_id: task}
    service = WorkflowService(
        workspace_manager=WorkspaceManager(workspace_root=str(__import__("tempfile").mkdtemp())),
        tasks=tasks,
        agents_provider=lambda: {},
        enqueue_task=lambda child: None,
        persist_task=lambda child: None,
        record_trace=lambda task, name, detail: None,
    )

    assert service.handle_task_success(task) == []
    assert task.children == []
