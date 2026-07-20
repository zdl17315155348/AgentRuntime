from __future__ import annotations

from aruntime.backends.base import AgentBackend, BackendExecutionRequest, BackendExecutionResult, EmitEvent
from aruntime.core.models import AgentBackendConfig, AgentBackendType


class LegacyLLMBackend(AgentBackend):
    def __init__(self, config: AgentBackendConfig, dependencies: dict):
        self.config = config
        self.llm_gateway = dependencies["llm_gateway"]

    async def prepare(self, request: BackendExecutionRequest) -> None:
        return None

    async def execute(self, request: BackendExecutionRequest, emit_event: EmitEvent) -> BackendExecutionResult:
        logical_context_reuse_hit = False
        execution = request.runtime_context.get("execution", {})
        if isinstance(execution, dict):
            logical_context_reuse_hit = bool(
                execution.get("logical_context_reuse_hit")
                or execution.get("prefix_cache_hit")
                or execution.get("cache_hit")
            )
        llm_result = self.llm_gateway.chat_with_stats(
            request.system_prompt,
            request.user_message,
            prefix_cache_hit=logical_context_reuse_hit,
        )
        return BackendExecutionResult(
            status="SUCCESS",
            output=llm_result.output,
            backend_type=AgentBackendType.LEGACY_LLM.value,
            usage=llm_result.to_dict(),
        )

    async def cancel(self, attempt_id: str) -> None:
        return None

    async def cleanup(self, request: BackendExecutionRequest) -> None:
        return None
