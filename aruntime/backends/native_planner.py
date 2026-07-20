from __future__ import annotations

import json

from aruntime.backends.base import BackendExecutionRequest, BackendExecutionResult, EmitEvent
from aruntime.backends.legacy_llm import LegacyLLMBackend
from aruntime.core.models import AgentBackendType
from applications.incident_repair.planning import DirectDeepSeekLLMAdapter, LocalRepositoryInspector, PlannerPipeline


class NativePlannerBackend(LegacyLLMBackend):
    def __init__(self, config, dependencies: dict):
        super().__init__(config, dependencies)
        self.pipeline = dependencies.get("planner_pipeline") or PlannerPipeline()

    async def execute(self, request: BackendExecutionRequest, emit_event: EmitEvent) -> BackendExecutionResult:
        if not request.workspace.workspace_path:
            return BackendExecutionResult(status="FAILED", error="workspace_path is required", backend_type=AgentBackendType.NATIVE_PLANNER.value)
        goal = str(request.task_input.get("request") or request.user_message)
        roles = request.runtime_context.get("available_roles", ["coder", "tester", "reviewer"])
        if not isinstance(roles, list) or not roles:
            roles = ["coder", "tester", "reviewer"]
        await emit_event({"name": "planner.repo_scan"})
        result = await self.pipeline.execute(
            goal=goal,
            system_prompt=request.system_prompt,
            inspector=LocalRepositoryInspector(request.workspace.workspace_path),
            llm=DirectDeepSeekLLMAdapter(self.llm_gateway),
            available_roles=[str(role) for role in roles],
            max_inspection_files=self.config.max_inspection_files,
        )
        return BackendExecutionResult(
            status="SUCCESS",
            output=json.dumps({"inspection": result.inspection.model_dump(mode="json"), "plan": result.plan.model_dump(mode="json")}, ensure_ascii=False),
            backend_type=AgentBackendType.NATIVE_PLANNER.value,
            usage={},
        )
