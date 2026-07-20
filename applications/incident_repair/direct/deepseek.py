from __future__ import annotations

from typing import Any


class DirectDeepSeekExecutor:
    async def execute_plan(self, system_prompt: str, goal: str, inspection: dict[str, Any]) -> dict[str, Any]:
        return {
            "version": "1.0",
            "summary": "direct baseline plan",
            "tasks": [
                {
                    "local_id": "coder_main",
                    "role": "coder",
                    "goal": goal,
                    "dependencies": [],
                }
            ],
            "inspection": inspection,
        }
