from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from applications.incident_repair.config import IncidentRunConfig
from applications.incident_repair.direct.codex import DirectCodexExecutor, _prepare_codex_home, last_agent_message
from applications.incident_repair.direct.deepseek import DirectDeepSeekExecutor
from applications.incident_repair.direct.tool import run_pytest_direct
from applications.incident_repair.direct.workspace import DirectWorkspaceManager
from applications.incident_repair.execution.base import AgentExecutionRequest, AgentExecutionResult, ExecutionProvider
from applications.incident_repair.execution.instrumentation import ExecutionTimer
from applications.incident_repair.schemas import ReviewSummaryModel


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
                available_roles = request.task_input.get("available_roles")
                if not isinstance(available_roles, list) or not available_roles:
                    available_roles = ["coder", "tester", "reviewer"]
                result = await self.deepseek.execute_plan(request.system_prompt, request.goal, request.source_repo, [str(role) for role in available_roles])
                return AgentExecutionResult(status="SUCCESS", structured_result=result, output=str(result), metrics=timer.finish(queue_wait_ms=queue_wait_ms))
            if request.backend == "direct_tool":
                workspace = None
                workspace_path = request.workspace_path or request.source_repo
                try:
                    if request.role == "tester" and isinstance(request.task_input, dict) and request.task_input.get("integrated_commit"):
                        workspace = self.workspace_manager.create_attempt_workspace(
                            request.source_repo,
                            request.graph_node,
                            request.idempotency_key[:16],
                            str(request.task_input["integrated_commit"]),
                            read_only=True,
                            root_task_id=request.run_id,
                        )
                        workspace_path = workspace.workspace_path or workspace_path
                    summary = await run_pytest_direct(workspace_path, request.timeout_s)
                except Exception as exc:
                    if workspace is not None:
                        self.workspace_manager.cleanup_workspace(workspace, force=True)
                    return AgentExecutionResult(status="FAILED", error_message=str(exc), workspace_path=workspace_path, metrics=timer.finish(queue_wait_ms=queue_wait_ms))
                if workspace is not None:
                    self.workspace_manager.cleanup_workspace(workspace, force=True)
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
                artifact_store = getattr(self.workspace_manager, "artifact_store", None)
                if artifact_store is None:
                    artifact_dir = Path(workspace.workspace_path or request.source_repo)
                else:
                    artifact_dir = Path(artifact_store.attempt_dir(request.run_id, request.idempotency_key[:16]))
                artifact_dir.mkdir(parents=True, exist_ok=True)
                codex_home = artifact_dir / "codex-home"
                _prepare_codex_home(str(codex_home), as_home=True)
                final_json = str(artifact_dir / ".codex-final.json")
                events_jsonl = str(artifact_dir / ".codex-events.jsonl")
                rc, stdout, stderr, _pid = await self.codex.execute(
                    request.goal,
                    workspace.workspace_path or request.source_repo,
                    request.role,
                    request.timeout_s,
                    system_prompt=request.system_prompt,
                    task_input=request.task_input,
                    runtime_context={"context_refs": request.context_refs, "artifact_refs": request.artifact_refs, "base_commit": request.base_commit},
                    output_last_message=final_json,
                    codex_home=str(codex_home),
                )
                if stdout:
                    Path(events_jsonl).write_text(stdout, encoding="utf-8")
                final_output = Path(final_json).read_text(encoding="utf-8", errors="replace") if Path(final_json).exists() else last_agent_message(stdout)
                if request.role == "reviewer":
                    try:
                        review = ReviewSummaryModel.model_validate_json(final_output)
                        structured = review.model_dump()
                        status = "SUCCESS"
                        error = None
                    except Exception as exc:
                        structured = {"approved": False, "requirements_covered": [], "issues": [str(exc)], "summary": "invalid reviewer output", "artifact_id": None}
                        status = "FAILED"
                        error = str(exc)
                    return AgentExecutionResult(
                        status=status,
                        output=final_output,
                        error_message=error or stderr or None,
                        workspace_path=workspace.workspace_path,
                        structured_result=structured,
                        metrics=timer.finish(queue_wait_ms=queue_wait_ms),
                    )
                patch = self.workspace_manager.create_patch_artifact(workspace, request.graph_node, request.idempotency_key[:16], root_task_id=request.run_id)
                error = None
                if rc != 0:
                    details = [f"codex exited {rc}" if rc is not None else "codex timeout"]
                    if stderr.strip():
                        details.append(f"stderr: {stderr.strip()[:1000]}")
                    if final_output.strip():
                        details.append(f"last_message: {final_output.strip()[:1000]}")
                    error = " | ".join(details)
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
                    output=final_output,
                    error_message=error,
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
