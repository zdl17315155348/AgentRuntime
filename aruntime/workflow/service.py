from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable

from aruntime.core.models import AgentBackendType, ArtifactReference, FailurePolicy, TaskSpec, TaskStatus, WorkspaceSpec
from aruntime.planner.materializer import materialize_plan
from aruntime.planner.models import PlanSpec
from aruntime.workspace.manager import WorkspaceManager


class WorkflowService:
    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        tasks: dict[str, TaskSpec],
        agents_provider: Callable[[], dict],
        enqueue_task: Callable[[TaskSpec], None],
        record_trace,
        persist_task,
        context_manager=None,
        max_repair_rounds: int = 2,
    ):
        self.workspace_manager = workspace_manager
        self.tasks = tasks
        self.agents_provider = agents_provider
        self.enqueue_task = enqueue_task
        self.record_trace = record_trace
        self.persist_task = persist_task
        self.context_manager = context_manager
        self.max_repair_rounds = max_repair_rounds
        self.integration_commits: dict[str, str] = {}
        self.integration_workspaces: dict[str, str] = {}
        self.applied_artifacts: dict[str, set[str]] = {}
        self.repair_rounds: dict[str, int] = {}

    def handle_task_success(self, task: TaskSpec) -> list[TaskSpec]:
        created: list[TaskSpec] = []
        if task.required_backend == AgentBackendType.NATIVE_PLANNER and not bool((task.task_input or {}).get("graph_managed")):
            created.extend(self._materialize_planner(task))
        if (task.task_role or "").lower() in {"coder", "repair"}:
            self._integrate_root_patches(task)
        return created

    def handle_task_failure(self, task: TaskSpec) -> list[TaskSpec]:
        if (task.task_role or "").lower() != "tester":
            return []
        root = task.root_task_id or task.task_id
        round_id = self.repair_rounds.get(root, 0)
        if round_id >= self.max_repair_rounds:
            return []
        agents = self.agents_provider()
        repair_agent = next((name for name, agent in agents.items() if agent.capability.can_code and (agent.capability.can_test or name == "repair")), None)
        if repair_agent is None:
            return []
        self.repair_rounds[root] = round_id + 1
        repair = TaskSpec(
            agent_name=repair_agent,
            task_input={
                "request": "Repair failing tests without precomputed patch.",
                "failed_tester_task": task.task_id,
                "failed_output": task.error or (task.result or {}).get("output", ""),
                "integration_commit": self.integration_commits.get(root, ""),
            },
            context_id=task.context_id,
            parent_task_id=task.parent_task_id or task.task_id,
            root_task_id=root,
            task_role="repair",
            required_backend=AgentBackendType.CODEX_CLI,
            workspace=WorkspaceSpec(
                source_repo=(task.workspace.source_repo if task.workspace else os.getcwd()),
                base_ref=self.integration_commits.get(root) or (task.workspace.base_commit if task.workspace else "HEAD") or "HEAD",
            ),
            trace_id=task.trace_id,
            required_capability={"can_code": True, "language": "python"},
            failure_policy=FailurePolicy(mode="fail_closed", max_retries=0),
        )
        tester = TaskSpec(
            agent_name=None,
            task_input=task.task_input,
            context_id=task.context_id,
            parent_task_id=repair.task_id,
            root_task_id=root,
            task_role="tester",
            required_backend=AgentBackendType.DIRECT_TOOL,
            workspace=WorkspaceSpec(
                source_repo=(task.workspace.source_repo if task.workspace else os.getcwd()),
                base_ref=self.integration_commits.get(root) or (task.workspace.base_commit if task.workspace else "HEAD") or "HEAD",
                read_only=True,
            ),
            trace_id=task.trace_id,
            dependencies=[repair.task_id],
            required_capability={"can_test": True, "tool": "run_pytest"},
        )
        repair.children.append(tester.task_id)
        for item in (repair, tester):
            self.tasks[item.task_id] = item
            self.enqueue_task(item)
            self.persist_task(item)
        self.record_trace(repair, "workflow.repair.created", {"failed_tester_task": task.task_id, "round": self.repair_rounds[root]})
        return [repair, tester]

    def workspace_for_task(self, task: TaskSpec) -> WorkspaceSpec | None:
        root = task.root_task_id or task.task_id
        if (task.task_role or "").lower() in {"tester", "reviewer"} and self.integration_commits.get(root):
            base = task.workspace or WorkspaceSpec(source_repo=os.getcwd())
            return WorkspaceSpec(
                source_repo=base.source_repo,
                base_ref=self.integration_commits[root],
                base_commit=self.integration_commits[root],
                read_only=(task.task_role or "").lower() != "reviewer" or True,
            )
        return task.workspace

    def _materialize_planner(self, task: TaskSpec) -> list[TaskSpec]:
        output = ((task.result or {}).get("output") or "")
        try:
            payload = json.loads(output)
            plan = PlanSpec(**payload["plan"])
            if isinstance(task.result, dict):
                task.result["inspection"] = payload.get("inspection") or {}
                task.result["plan_summary"] = payload["plan"].get("summary", "")
        except Exception as exc:
            task.error = f"planner output materialization failed: {exc}"
            return []
        children = materialize_plan(task, plan)
        for child in children:
            agent_name = self._select_agent_for_child(child)
            child.agent_name = agent_name
            self.tasks[child.task_id] = child
            task.children.append(child.task_id)
            self.enqueue_task(child)
            self.persist_task(child)
            self.record_trace(child, "workflow.task.materialized", {"parent_task_id": task.task_id, "role": child.task_role})
        self.persist_task(task)
        return children

    def _select_agent_for_child(self, task: TaskSpec) -> str | None:
        agents = self.agents_provider()
        if task.task_role == "tester":
            return next((name for name, agent in agents.items() if agent.capability.can_test), None)
        if task.task_role == "reviewer":
            return next((name for name, agent in agents.items() if agent.capability.can_review), None)
        if task.task_role in {"coder", "repair"}:
            return next((name for name, agent in agents.items() if agent.capability.can_code), None)
        return None

    def _integrate_root_patches(self, trigger_task: TaskSpec) -> None:
        root = trigger_task.root_task_id or trigger_task.task_id
        code_tasks = [
            task for task in self.tasks.values()
            if (task.root_task_id or task.task_id) == root and (task.task_role or "").lower() in {"coder", "repair"} and task.status == TaskStatus.SUCCESS
        ]
        artifacts: list[ArtifactReference] = []
        for task in sorted(code_tasks, key=lambda item: item.task_id):
            for attempt in task.attempts:
                artifacts.extend([artifact for artifact in attempt.artifacts if artifact.artifact_type == "patch"])
        if not artifacts:
            return
        source_repo = (trigger_task.workspace.source_repo if trigger_task.workspace else os.getcwd())
        base_ref = self.integration_commits.get(root) or (trigger_task.workspace.base_commit if trigger_task.workspace else None) or "HEAD"
        base_commit = self._git(Path(source_repo), "rev-parse", base_ref).strip()
        integration = self.workspace_manager.create_attempt_workspace(source_repo, root, f"{root}:integration:{len(artifacts)}", base_commit, False, root)
        path = Path(integration.workspace_path)
        applied: list[str] = []
        for artifact in artifacts:
            if artifact.artifact_id in self.applied_artifacts.get(root, set()):
                continue
            check = subprocess.run(["git", "-C", str(path), "apply", "--check", artifact.path], capture_output=True, text=True, check=False)
            if check.returncode != 0:
                self.record_trace(trigger_task, "workflow.integration.conflict", {"artifact_id": artifact.artifact_id, "error": check.stderr or check.stdout})
                return
            apply = subprocess.run(["git", "-C", str(path), "apply", "--3way", artifact.path], capture_output=True, text=True, check=False)
            if apply.returncode != 0:
                self.record_trace(trigger_task, "workflow.integration.conflict", {"artifact_id": artifact.artifact_id, "error": apply.stderr or apply.stdout})
                return
            applied.append(artifact.artifact_id)
        if not applied:
            return
        subprocess.run(["git", "-C", str(path), "diff", "--check"], capture_output=True, text=True, check=True)
        subprocess.run(["git", "-C", str(path), "add", "-A"], capture_output=True, text=True, check=True)
        status = subprocess.run(["git", "-C", str(path), "diff", "--cached", "--quiet"], capture_output=True, text=True, check=False)
        if status.returncode == 0:
            return
        subprocess.run(
            ["git", "-C", str(path), "-c", "user.name=AgentRuntime", "-c", "user.email=runtime@local", "commit", "-m", "runtime: integrate agent patches"],
            capture_output=True,
            text=True,
            check=True,
        )
        commit = self._git(path, "rev-parse", "HEAD").strip()
        self.integration_commits[root] = commit
        self.integration_workspaces[root] = str(path)
        self.applied_artifacts.setdefault(root, set()).update(applied)
        self.record_trace(trigger_task, "workflow.integration.commit", {"commit": commit, "artifacts": applied})

    def _git(self, cwd: Path, *args: str) -> str:
        proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout)
        return proc.stdout
