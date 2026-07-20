from __future__ import annotations

from aruntime.core.models import TaskSpec


def summarize_attempts(tasks: list[TaskSpec]) -> list[dict]:
    return [attempt.model_dump(mode="json") for task in tasks for attempt in task.attempts]
