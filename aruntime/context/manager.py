import json
import hashlib
import time
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeContext:
    context_id: str
    shared_data: dict[str, Any] = field(default_factory=dict)
    private_data: dict[str, dict[str, Any]] = field(default_factory=dict)
    readonly_data: dict[str, Any] = field(default_factory=dict)
    context_diff: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    compressed: bool = False
    version: int = 0
    prefix_cache_key: str = ""
    prefix_block_id: str = ""
    reuse_count: int = 0
    original_tokens: int = 0
    saved_tokens: int = 0
    cache_hits: int = 0
    build_time_ms_total: float = 0.0
    previous_versions: list[dict[str, Any]] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)


class ContextManager:
    def __init__(self, compress_threshold_chars: int = 8000, max_contexts: int = 256, ttl_seconds: int = 3600):
        self.compress_threshold_chars = compress_threshold_chars
        self.max_contexts = max_contexts
        self.ttl_seconds = ttl_seconds
        self._contexts: OrderedDict[str, RuntimeContext] = OrderedDict()
        self._reuse_hits = 0
        self._compression_count = 0
        self._build_hits = 0
        self._execution_cache: dict[str, int] = {}
        self._cache_hits = 0
        self._original_tokens = 0
        self._saved_tokens = 0
        self._input_tokens_after = 0
        self._build_time_ms_total = 0.0

    def get_context(self, context_id: str) -> RuntimeContext | None:
        return self._contexts.get(context_id)

    def record_task_context(
        self,
        context_id: str,
        agent_name: str,
        shared_data: dict[str, Any] | None = None,
        private_data: dict[str, Any] | None = None,
        readonly_data: dict[str, Any] | None = None,
    ) -> RuntimeContext:
        context = self._contexts.get(context_id)
        if context is not None:
            context.updated_at = time.time()
            self._contexts.move_to_end(context_id)
        if context is None:
            context = RuntimeContext(context_id=context_id)
            self._contexts[context_id] = context
        else:
            self._reuse_hits += 1
            context.reuse_count += 1
            if context.compressed and context.shared_data.get("__structured_summary__"):
                return context

        diff: dict[str, Any] = {}
        if shared_data:
            diff["shared"] = deepcopy(shared_data)
            context.shared_data.update(deepcopy(shared_data))
            context.version += 1
        if private_data is not None:
            diff["private"] = {agent_name: deepcopy(private_data)}
            current_private = context.private_data.get(agent_name, {})
            current_private.update(deepcopy(private_data))
            context.private_data[agent_name] = current_private
            context.version += 1
        if readonly_data:
            diff["readonly"] = deepcopy(readonly_data)
            for key, value in deepcopy(readonly_data).items():
                if key not in context.readonly_data:
                    context.readonly_data[key] = value
            context.version += 1

        context.context_diff = diff
        context.summary = self._summary(context)
        self._compress_if_needed(context)
        context.prefix_cache_key = self._cache_key(context)
        context.prefix_block_id = self._prefix_block_id(context.prefix_cache_key)
        self._evict_expired()
        self._evict_lru()
        return context

    def build_agent_context(self, context_id: str, agent_name: str) -> dict[str, Any]:
        started = time.perf_counter()
        context = self._contexts.get(context_id)
        if context is None:
            return {
                "context_id": context_id,
                "shared": {},
                "private": {},
                "readonly": {},
                "compressed": False,
                "semantic": {
                    "shared_context": {},
                    "private_context": {},
                    "readonly_context": {},
                    "context_version": 0,
                    "context_diff": {},
                    "summary": "",
                    "version": 0,
                    "shared_keys": [],
                    "private_keys": [],
                    "readonly_keys": [],
                },
                "execution": {
                    "prefix_cache_key": "",
                    "prefix_hash": "",
                    "prefix_block_id": "",
                    "reuse_count": 0,
                    "token_count": 0,
                    "input_token_before": 0,
                    "input_token_after": 0,
                    "reused_tokens": 0,
                    "saved_tokens": 0,
                    "cache_hit": False,
                    "logical_context_reuse_hit": False,
                    "cache_hit_ratio": 0.0,
                },
            }

        context.updated_at = time.time()
        self._contexts.move_to_end(context_id)
        self._build_hits += 1
        shared = deepcopy(context.shared_data)
        private = deepcopy(context.private_data.get(agent_name, {}))
        readonly = deepcopy(context.readonly_data)
        token_count = self._estimate_tokens({
            "shared": shared,
            "private": private,
            "readonly": readonly,
        })
        cache_key = context.prefix_cache_key or self._cache_key(context)
        prefix_hash = self._prefix_hash(cache_key)
        prefix_block_id = context.prefix_block_id or self._prefix_block_id(cache_key)
        previous_tokens = self._execution_cache.get(cache_key)
        cache_hit = previous_tokens is not None
        reused_tokens = previous_tokens if previous_tokens is not None else 0
        saved_tokens = min(reused_tokens, token_count)
        input_token_after = max(token_count - saved_tokens, 0)
        build_time_ms = round((time.perf_counter() - started) * 1000, 3)

        context.original_tokens += token_count
        context.saved_tokens += saved_tokens
        context.build_time_ms_total += build_time_ms
        self._original_tokens += token_count
        self._saved_tokens += saved_tokens
        self._input_tokens_after += input_token_after
        self._build_time_ms_total += build_time_ms
        if cache_hit:
            context.cache_hits += 1
            self._cache_hits += 1
        self._execution_cache[cache_key] = token_count

        return {
            "context_id": context.context_id,
            "shared": shared,
            "private": private,
            "readonly": readonly,
            "compressed": context.compressed,
            "semantic": {
                "shared_context": shared,
                "private_context": private,
                "readonly_context": readonly,
                "context_version": context.version,
                "context_diff": deepcopy(context.context_diff),
                "summary": context.summary,
                "version": context.version,
                "shared_keys": sorted(shared.keys()),
                "private_keys": sorted(private.keys()),
                "readonly_keys": sorted(readonly.keys()),
            },
            "execution": {
                "prefix_cache_key": cache_key,
                "prefix_hash": prefix_hash,
                "prefix_block_id": prefix_block_id,
                "reuse_count": context.reuse_count,
                "token_count": token_count,
                "input_token_before": token_count,
                "input_token_after": input_token_after,
                "reused_tokens": reused_tokens,
                "saved_tokens": saved_tokens,
                "cache_hit": cache_hit,
                "logical_context_reuse_hit": cache_hit,
                "prefix_cache_hit": cache_hit,
                "cache_hit_ratio": self._ratio(self._cache_hits, self._build_hits),
                "logical_context_reuse_hit_ratio": self._ratio(self._cache_hits, self._build_hits),
                "context_build_time_ms": build_time_ms,
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
            "input_token_before": self._original_tokens,
            "input_token_after": self._input_tokens_after,
            "token_saved_ratio": self._ratio(self._saved_tokens, self._original_tokens),
            "token_saving_ratio": self._ratio(self._saved_tokens, self._original_tokens),
            "context_build_time_ms": round(self._build_time_ms_total, 3),
            "context_build_time_ms_avg": round(self._build_time_ms_total / self._build_hits, 3) if self._build_hits else 0.0,
            "prefix_hit_ratio": self._ratio(self._cache_hits, self._build_hits),
            "logical_context_reuse_hits": self._cache_hits,
            "logical_context_reuse_hit_ratio": self._ratio(self._cache_hits, self._build_hits),
        }

    def rollback_context(self, context_id: str) -> bool:
        context = self._contexts.get(context_id)
        if context is None or not context.previous_versions:
            return False
        previous = context.previous_versions.pop()
        context.shared_data = previous["shared"]
        context.private_data = previous["private"]
        context.readonly_data = previous["readonly"]
        context.summary = previous["summary"]
        context.compressed = previous["compressed"]
        context.version += 1
        context.context_diff = {"rollback": True}
        context.prefix_cache_key = self._cache_key(context)
        context.prefix_block_id = self._prefix_block_id(context.prefix_cache_key)
        return True

    def _compress_if_needed(self, context: RuntimeContext) -> None:
        if context.compressed and context.shared_data.get("__structured_summary__"):
            return

        raw_context = json.dumps(
            {
                "shared": context.shared_data,
                "private": context.private_data,
                "readonly": context.readonly_data,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        content_size = sum(
            len(json.dumps(part, ensure_ascii=False, sort_keys=True))
            for part in (context.shared_data, context.private_data, context.readonly_data)
        )
        if content_size <= self.compress_threshold_chars:
            return

        context.previous_versions.append({
            "shared": deepcopy(context.shared_data),
            "private": deepcopy(context.private_data),
            "readonly": deepcopy(context.readonly_data),
            "summary": context.summary,
            "compressed": context.compressed,
        })
        context.shared_data = self._structured_summary("shared", context.shared_data)
        context.private_data = {
            agent: self._structured_summary(f"private:{agent}", payload)
            for agent, payload in context.private_data.items()
        }
        context.summary = f"structured_summary chars={len(raw_context)} version={context.version}"
        context.compressed = True
        context.version += 1
        self._compression_count += 1

    def _structured_summary(self, label: str, payload: dict[str, Any]) -> dict[str, Any]:
        keys = sorted(payload.keys())
        important = {
            key: deepcopy(payload[key])
            for key in keys
            if key in {"goal", "task", "constraints", "tool_results", "entities", "requirements"}
        }
        return {
            "__structured_summary__": True,
            "label": label,
            "keys": keys[:50],
            "important": important,
        }

    def _cache_key(self, context: RuntimeContext) -> str:
        raw_shared = json.dumps(
            {
                "shared": context.shared_data,
                "readonly": context.readonly_data,
                "summary": context.summary,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return f"{context.context_id}:v{context.version}:{raw_shared}"

    def _prefix_hash(self, cache_key: str) -> str:
        return hashlib.sha256(cache_key.encode("utf-8")).hexdigest()

    def _prefix_block_id(self, cache_key: str) -> str:
        return f"pblk_{self._prefix_hash(cache_key)[:16]}" if cache_key else ""

    def _summary(self, context: RuntimeContext) -> str:
        return (
            f"shared={len(context.shared_data)}, "
            f"private_agents={len(context.private_data)}, "
            f"readonly={len(context.readonly_data)}, "
            f"version={context.version}"
        )

    def _estimate_tokens(self, payload: dict[str, Any]) -> int:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return max(1, (len(raw) + 3) // 4)

    def _ratio(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(numerator / denominator, 4)

    def _evict_expired(self) -> None:
        if self.ttl_seconds <= 0:
            return
        now = time.time()
        for context_id, context in list(self._contexts.items()):
            if now - context.updated_at > self.ttl_seconds:
                self._contexts.pop(context_id, None)

    def _evict_lru(self) -> None:
        while len(self._contexts) > self.max_contexts:
            self._contexts.popitem(last=False)
