from __future__ import annotations

import json
import time
from typing import Any

from aruntime.api.client import AgentRuntimeClient

from applications.incident_repair.config import IncidentRunConfig
from applications.incident_repair.execution.base import AgentExecutionRequest, AgentExecutionResult, ExecutionProvider
from applications.incident_repair.execution.instrumentation import ExecutionTimer
from applications.incident_repair.schemas import CoderResultModel, ReviewSummaryModel, TestSummaryModel


class RuntimeSystemError(Exception):
    pass


class AgentTaskFailedError(Exception):
    pass


class AgentRuntimeExecutionProvider(ExecutionProvider):
    def __init__(self, config: IncidentRunConfig, dependencies: dict[str, Any] | None = None):
        self.config = config
        self.dependencies = dependencies or {}
        self.client: AgentRuntimeClient = self.dependencies.get("client") or AgentRuntimeClient()

    @property
    def mode(self) -> str:
        return "runtime"

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        timer = ExecutionTimer()
        payload = {
            "goal": request.goal,
            "system_prompt": request.system_prompt,
            "source_repo": request.source_repo,
            "base_commit": request.base_commit,
            "context_refs": request.context_refs,
            "artifact_refs": request.artifact_refs,
            "graph": {
                "run_id": request.run_id,
                "thread_id": request.thread_id,
                "node": request.graph_node,
                "step": request.graph_step,
            },
            "graph_managed": True,
        }
        payload.update(request.task_input)
        task = self.client.submit_task(
            self._agent_for_role(request.role),
            payload,
            resource_request=request.resource_request,
            required_capability=self._capability_for_role(request.role),
            required_backend=self._backend_for_request(request),
            timeout_ms=request.timeout_s * 1000,
            task_role=request.role,
            trace_id=request.thread_id,
            root_task_id=request.run_id,
            idempotency_key=request.idempotency_key,
            failure_policy=self._failure_policy_for_role(request.role),
        )
        task_id = str(task["task_id"])
        timer.mark_execution_started()
        result = self.client.wait_task(task_id, request.timeout_s + 30)
        return self._convert_result(request, result, timer)

    async def cancel_run(self, run_id: str) -> None:
        task_ids = self.dependencies.get("run_task_ids", {}).get(run_id, set())
        for task_id in list(task_ids):
            try:
                self.client.cancel_task(task_id)
            except Exception:
                continue

    async def inject_fault(self, run_id: str, target: dict[str, Any]) -> dict[str, Any]:
        agent_name = str(target.get("agent_name") or target.get("role") or "")
        if not agent_name:
            return {"run_id": run_id, "injected": False, "reason": "missing agent_name"}
        return self.client.inject_worker_sigkill(agent_name)

    async def get_execution_snapshot(self, run_id: str) -> dict[str, Any]:
        return self.client.get_metrics()

    def _convert_result(self, request: AgentExecutionRequest, task: dict[str, Any], timer: ExecutionTimer) -> AgentExecutionResult:
        scheduler = task.get("scheduler") or {}
        result = task.get("result") or {}
        attempts = task.get("attempts") or []
        status = str(task.get("status") or "FAILED")
        if status not in ("SUCCESS", "FAILED", "TIMEOUT", "CANCELLED"):
            status = "FAILED"
            raise RuntimeSystemError(f"unexpected runtime task status: {task.get('status')}")
        if status == "SUCCESS" or self._result_has_output(result):
            structured = self._structured_result_for_backend(request, result)
        else:
            structured = {}
        patch_ref = None
        artifact_refs: list[str] = []
        artifacts = result.get("artifacts") if isinstance(result, dict) else None
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    continue
                artifact_refs.append(str(artifact.get("artifact_id") or ""))
                if artifact.get("artifact_type") == "patch":
                    patch_ref = {
                        "task_local_id": str(request.task_input.get("local_id") or request.graph_node),
                        "artifact_id": artifact.get("artifact_id"),
                        "patch_path": str(artifact.get("path") or ""),
                        "sha256": str(artifact.get("sha256") or ""),
                        "changed_files": list((artifact.get("metadata") or {}).get("changed_files", [])),
                    }
        metrics = timer.finish(
            queue_wait_ms=float(scheduler.get("queue_wait_ms") or 0),
            total_tokens=float((task.get("llm_usage") or {}).get("total_tokens") or 0),
        )
        return AgentExecutionResult(
            status=status,  # type: ignore[arg-type]
            output=str(result.get("output") if isinstance(result, dict) else result or ""),
            error_message=task.get("error") or None,
            runtime_task_id=str(task.get("task_id") or ""),
            attempt_ids=[str(attempt.get("attempt_id")) for attempt in attempts if isinstance(attempt, dict)],
            artifact_refs=[ref for ref in artifact_refs if ref],
            patch_ref=patch_ref,
            structured_result=structured,
            metrics=metrics,
        )

    def _structured_result_for_backend(self, request: AgentExecutionRequest, result: dict[str, Any]) -> dict[str, Any]:
        payload = self._json_payload(result)
        if not payload:
            raise RuntimeSystemError(f"empty structured output from {request.backend}")

        if request.backend == "deepseek":
            plan = payload.get("plan")
            return plan if isinstance(plan, dict) else payload

        if request.backend == "codex_cli":
            if request.role in ("coder", "repair"):
                return CoderResultModel.model_validate(payload).model_dump()
            if request.role == "reviewer":
                return ReviewSummaryModel.model_validate(payload).model_dump()
            return payload

        if request.backend == "direct_tool":
            return TestSummaryModel.model_validate(payload).model_dump()

        return payload

    def _json_payload(self, result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise RuntimeSystemError("invalid runtime result envelope")
        output = result.get("output")
        if isinstance(output, dict):
            return output
        if isinstance(output, str):
            if not output.strip():
                return {}
            try:
                payload = json.loads(output)
            except json.JSONDecodeError as exc:
                raise RuntimeSystemError(f"invalid structured output: {exc}") from exc
            if not isinstance(payload, dict):
                raise RuntimeSystemError("structured output must be a JSON object")
            return payload
        return {}

    def _result_has_output(self, result: dict[str, Any]) -> bool:
        if not isinstance(result, dict):
            return False
        output = result.get("output")
        if isinstance(output, dict):
            return bool(output)
        if isinstance(output, str):
            return bool(output.strip())
        return False

    def _agent_for_role(self, role: str) -> str | None:
        return {"planner": "architect", "coder": None, "repair": "repair", "tester": "tester", "reviewer": "reviewer", "integrator": None}.get(role)

    def _capability_for_role(self, role: str) -> dict[str, Any]:
        if role == "planner":
            return {"can_plan": True}
        if role in ("coder", "repair"):
            return {"can_code": True, "languages": ["python"]}
        if role == "tester":
            return {"can_test": True}
        return {}

    def _backend_for_request(self, request: AgentExecutionRequest) -> str | None:
        return {"deepseek": "native_planner", "codex_cli": "codex_cli", "direct_tool": "direct_tool"}.get(request.backend)

    def _failure_policy_for_role(self, role: str) -> dict[str, Any]:
        if role in ("coder", "repair"):
            return {"mode": "fallback", "max_retries": 1, "fallback_agent": "coder_b"}
        return {"mode": "retry", "max_retries": 0}
