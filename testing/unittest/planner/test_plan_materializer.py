from aruntime.core.models import AgentBackendType, WorkspaceSpec, TaskSpec
from aruntime.planner.materializer import materialize_plan
from aruntime.planner.models import PlanSpec, PlanTask


def test_materializer_maps_roles_to_backends():
    parent = TaskSpec(task_id="root", agent_name="architect", task_input={}, workspace=WorkspaceSpec(source_repo="/repo"))
    plan = PlanSpec(
        summary="x",
        tasks=[
            PlanTask(local_id="fix", role="coder", goal="fix"),
            PlanTask(local_id="test", role="tester", goal="test", dependencies=["fix"]),
            PlanTask(local_id="review", role="reviewer", goal="review", dependencies=["test"]),
        ],
    )

    tasks = materialize_plan(parent, plan)

    assert tasks[0].required_backend == AgentBackendType.CODEX_CLI
    assert tasks[1].required_backend == AgentBackendType.DIRECT_TOOL
    assert tasks[1].task_input["__tool"]["name"] == "run_pytest"
    assert tasks[2].root_task_id == "root"


def test_materializer_closes_codegen_and_test_failure_by_default():
    parent = TaskSpec(task_id="root", agent_name="architect", task_input={}, workspace=WorkspaceSpec(source_repo="/repo"))
    parent.result = {"inspection": {"files": {"app/auth.py": "content"}}, "plan_summary": "summary"}
    plan = PlanSpec(
        summary="x",
        tasks=[
            PlanTask(local_id="fix", role="coder", goal="fix"),
            PlanTask(local_id="test", role="tester", goal="test", dependencies=["fix"]),
            PlanTask(local_id="review", role="reviewer", goal="review", dependencies=["test"]),
        ],
    )

    tasks = materialize_plan(parent, plan)

    assert tasks[0].failure_policy.mode == "fail_closed"
    assert tasks[1].failure_policy.mode == "fail_closed"
    assert tasks[2].failure_policy.mode == "fail_open"
    assert tasks[0].task_input["planner_context"]["inspection"]["files"]["app/auth.py"] == "content"
