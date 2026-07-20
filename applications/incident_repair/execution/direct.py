from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from applications.incident_repair.config import IncidentRunConfig
from applications.incident_repair.direct.codex import DirectCodexExecutor, last_agent_message
from applications.incident_repair.direct.deepseek import DirectDeepSeekExecutor
from applications.incident_repair.direct.tool import run_pytest_direct
from applications.incident_repair.direct.workspace import DirectWorkspaceManager
from applications.incident_repair.execution.base import AgentExecutionRequest, AgentExecutionResult, ExecutionProvider
from applications.incident_repair.execution.instrumentation import ExecutionTimer


class DirectExecutionProvider(ExecutionProvider):
    def __init__(self, config: IncidentRunConfig, dependencies: dict[str, Any] | None = None):
        self.config = config
        self.dependencies = dependencies or {}
        self._semaphore = asyncio.Semaphore(config.max_concurrency)
        self.deepseek = self.dependencies.get("deepseek") or DirectDeepSeekExecutor()
        self.codex = self.dependencies.get("codex") or DirectCodexExecutor()
        self.workspace_manager = self.dependencies.get("workspace_manager") or DirectWorkspaceManager()
        self._cancelled: set[str] = set()

    @property
    def mode(self) -> str:
        return "direct"

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        timer = ExecutionTimer()
        wait_started = time.perf_counter()
        async with self._semaphore:
            queue_wait_ms = (time.perf_counter() - wait_started) * 1000
            timer.mark_execution_started()
            if request.run_id in self._cancelled:
                return AgentExecutionResult(status="CANCELLED", metrics=timer.finish(queue_wait_ms=queue_wait_ms))
            if request.backend == "deepseek":
                inspection = {"files": [], "searches": [], "summary": "direct inspection placeholder"}
                result = await self.deepseek.execute_plan(request.system_prompt, request.goal, inspection)
                return AgentExecutionResult(status="SUCCESS", structured_result=result, output=str(result), metrics=timer.finish(queue_wait_ms=queue_wait_ms))
            if request.backend == "direct_tool":
                workspace_path = request.workspace_path or request.source_repo
                summary = await run_pytest_direct(workspace_path, request.timeout_s)
                return AgentExecutionResult(status="SUCCESS", structured_result=summary, workspace_path=workspace_path, metrics=timer.finish(queue_wait_ms=queue_wait_ms, tool_calls=1))
            if request.backend == "codex_cli":
                workspace = self.workspace_manager.create_attempt_workspace(
                    request.source_repo,
                    request.graph_node,
                    request.idempotency_key[:16],
                    request.base_commit,
                    read_only=request.role == "reviewer",
                    root_task_id=request.run_id,
                )
                rc, stdout, stderr, _pid = await self.codex.execute(request.goal, workspace.workspace_path or request.source_repo, request.role, request.timeout_s)
                if request.role == "reviewer":
                    approved = rc == 0
                    return AgentExecutionResult(
                        status="SUCCESS" if rc == 0 else "FAILED",
                        output=last_agent_message(stdout),
                        error_message=stderr or None,
                        workspace_path=workspace.workspace_path,
                        structured_result={"approved": approved, "requirements_covered": [], "issues": [] if approved else [stderr or "review failed"], "artifact_id": None},
                        metrics=timer.finish(queue_wait_ms=queue_wait_ms),
                    )
                patch = self.workspace_manager.create_patch_artifact(workspace, request.graph_node, request.idempotency_key[:16], root_task_id=request.run_id)
                patch_ref = None
                if patch:
                    patch_ref = {
                        "task_local_id": str(request.task_input.get("local_id") or request.graph_node),
                        "artifact_id": patch.artifact_id,
                        "patch_path": patch.path,
                        "sha256": patch.sha256,
                        "changed_files": list(patch.metadata.get("changed_files", [])),
                    }
                return AgentExecutionResult(
                    status="SUCCESS" if rc == 0 else ("TIMEOUT" if rc is None else "FAILED"),
                    output=last_agent_message(stdout),
                    error_message=stderr or None,
                    workspace_path=workspace.workspace_path,
                    patch_ref=patch_ref,
                    metrics=timer.finish(queue_wait_ms=queue_wait_ms),
                )
            return AgentExecutionResult(status="FAILED", error_type="UnsupportedBackend", error_message=request.backend, metrics=timer.finish(queue_wait_ms=queue_wait_ms))

    async def cancel_run(self, run_id: str) -> None:
        self._cancelled.add(run_id)

    async def inject_fault(self, run_id: str, target: dict[str, Any]) -> dict[str, Any]:
        return {"run_id": run_id, "mode": self.mode, "injected": False, "reason": "direct fault injection is explicit per process"}

    async def get_execution_snapshot(self, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id, "mode": self.mode, "cancelled": run_id in self._cancelled}
