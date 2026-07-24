from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Protocol

from aruntime.llm.gateway import LLMResult


class PlannerLLM(Protocol):
    async def complete(self, system_prompt: str, prompt: str) -> LLMResult: ...


@dataclass
class DirectDeepSeekLLMAdapter:
    client: object

    async def complete(self, system_prompt: str, prompt: str) -> LLMResult:
        chat = self.client.chat_with_stats
        if inspect.iscoroutinefunction(chat):
            return await chat(system_prompt, prompt)
        result = await asyncio.to_thread(chat, system_prompt, prompt)
        if inspect.isawaitable(result):
            result = await result
        return result
