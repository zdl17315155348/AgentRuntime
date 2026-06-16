import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeContext:
    context_id: str
    shared_data: dict[str, Any] = field(default_factory=dict)
    private_data: dict[str, dict[str, Any]] = field(default_factory=dict)
    compressed: bool = False


class ContextManager:
    def __init__(self, compress_threshold_chars: int = 8000):
        self.compress_threshold_chars = compress_threshold_chars
        self._contexts: dict[str, RuntimeContext] = {}
        self._reuse_hits = 0
        self._compression_count = 0
        self._build_hits = 0

    def get_context(self, context_id: str) -> RuntimeContext | None:
        return self._contexts.get(context_id)

    def record_task_context(
        self,
        context_id: str,
        agent_name: str,
        shared_data: dict[str, Any] | None = None,
        private_data: dict[str, Any] | None = None,
    ) -> RuntimeContext:
        context = self._contexts.get(context_id)
        if context is None:
            context = RuntimeContext(context_id=context_id)
            self._contexts[context_id] = context
        else:
            self._reuse_hits += 1
            if context.compressed and "__compressed_summary__" in context.shared_data:
                context.private_data = {}
                return context

        if shared_data:
            context.shared_data.update(deepcopy(shared_data))
        if private_data is not None:
            current_private = context.private_data.get(agent_name, {})
            current_private.update(deepcopy(private_data))
            context.private_data[agent_name] = current_private

        self._compress_if_needed(context)
        return context

    def build_agent_context(self, context_id: str, agent_name: str) -> dict[str, Any]:
        context = self._contexts.get(context_id)
        if context is None:
            return {
                "context_id": context_id,
                "shared": {},
                "private": {},
                "compressed": False,
            }

        self._build_hits += 1
        return {
            "context_id": context.context_id,
            "shared": deepcopy(context.shared_data),
            "private": deepcopy(context.private_data.get(agent_name, {})),
            "compressed": context.compressed,
        }

    def get_metrics(self) -> dict[str, int]:
        return {
            "total_contexts": len(self._contexts),
            "reuse_hits": self._reuse_hits,
            "compression_count": self._compression_count,
            "build_hits": self._build_hits,
        }

    def _compress_if_needed(self, context: RuntimeContext) -> None:
        if context.compressed and "__compressed_summary__" in context.shared_data:
            return

        raw_context = json.dumps(
            {
                "shared": context.shared_data,
                "private": context.private_data,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if len(raw_context) <= self.compress_threshold_chars:
            return

        context.shared_data = {
            "__compressed_summary__": f"Context compressed from {len(raw_context)} chars"
        }
        context.private_data = {}
        context.compressed = True
        self._compression_count += 1
