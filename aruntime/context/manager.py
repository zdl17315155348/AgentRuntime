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
    version: int = 0
    prefix_cache_key: str = ""
    original_tokens: int = 0
    saved_tokens: int = 0
    cache_hits: int = 0


class ContextManager:
    def __init__(self, compress_threshold_chars: int = 8000):
        self.compress_threshold_chars = compress_threshold_chars
        self._contexts: dict[str, RuntimeContext] = {}
        self._reuse_hits = 0
        self._compression_count = 0
        self._build_hits = 0
        self._execution_cache: dict[str, int] = {}
        self._cache_hits = 0
        self._original_tokens = 0
        self._saved_tokens = 0

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
            context.version += 1
        if private_data is not None:
            current_private = context.private_data.get(agent_name, {})
            current_private.update(deepcopy(private_data))
            context.private_data[agent_name] = current_private
            context.version += 1

        self._compress_if_needed(context)
        context.prefix_cache_key = self._cache_key(context)
        return context

    def build_agent_context(self, context_id: str, agent_name: str) -> dict[str, Any]:
        context = self._contexts.get(context_id)
        if context is None:
            return {
                "context_id": context_id,
                "shared": {},
                "private": {},
                "compressed": False,
                "semantic": {
                    "version": 0,
                    "shared_keys": [],
                    "private_keys": [],
                },
                "execution": {
                    "prefix_cache_key": "",
                    "token_count": 0,
                    "reused_tokens": 0,
                    "saved_tokens": 0,
                    "cache_hit": False,
                    "cache_hit_ratio": 0.0,
                },
            }

        self._build_hits += 1
        shared = deepcopy(context.shared_data)
        private = deepcopy(context.private_data.get(agent_name, {}))
        token_count = self._estimate_tokens({
            "shared": shared,
            "private": private,
        })
        cache_key = context.prefix_cache_key or self._cache_key(context)
        previous_tokens = self._execution_cache.get(cache_key)
        cache_hit = previous_tokens is not None
        reused_tokens = previous_tokens if previous_tokens is not None else 0
        saved_tokens = min(reused_tokens, token_count)

        context.original_tokens += token_count
        context.saved_tokens += saved_tokens
        self._original_tokens += token_count
        self._saved_tokens += saved_tokens
        if cache_hit:
            context.cache_hits += 1
            self._cache_hits += 1
        self._execution_cache[cache_key] = token_count

        return {
            "context_id": context.context_id,
            "shared": shared,
            "private": private,
            "compressed": context.compressed,
            "semantic": {
                "version": context.version,
                "shared_keys": sorted(shared.keys()),
                "private_keys": sorted(private.keys()),
            },
            "execution": {
                "prefix_cache_key": cache_key,
                "token_count": token_count,
                "reused_tokens": reused_tokens,
                "saved_tokens": saved_tokens,
                "cache_hit": cache_hit,
                "cache_hit_ratio": self._ratio(self._cache_hits, self._build_hits),
            },
        }

    def get_metrics(self) -> dict[str, int | float]:
        return {
            "total_contexts": len(self._contexts),
            "reuse_hits": self._reuse_hits,
            "compression_count": self._compression_count,
            "build_hits": self._build_hits,
            "cache_hits": self._cache_hits,
            "cache_hit_ratio": self._ratio(self._cache_hits, self._build_hits),
            "original_tokens": self._original_tokens,
            "saved_tokens": self._saved_tokens,
            "token_saved_ratio": self._ratio(self._saved_tokens, self._original_tokens),
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
        context.version += 1
        self._compression_count += 1

    def _cache_key(self, context: RuntimeContext) -> str:
        raw_shared = json.dumps(context.shared_data, ensure_ascii=False, sort_keys=True)
        return f"{context.context_id}:v{context.version}:{raw_shared}"

    def _estimate_tokens(self, payload: dict[str, Any]) -> int:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return max(1, (len(raw) + 3) // 4)

    def _ratio(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(numerator / denominator, 4)
