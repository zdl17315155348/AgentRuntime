from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from aruntime.llm.gateway import LLMResult


class PlannerLLM(Protocol):
    async def complete(self, system_prompt: str, prompt: str) -> LLMResult: ...


@dataclass
class DirectDeepSeekLLMAdapter:
    client: object

    async def complete(self, system_prompt: str, prompt: str) -> LLMResult:
        result = self.client.chat_with_stats(system_prompt, prompt)
        if hasattr(result, "__await__"):
            result = await result
        return result
