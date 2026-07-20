from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class RunEvent(BaseModel):
    event_id: int
    timestamp: float
    run_id: str
    thread_id: str
    execution_mode: str
    layer: Literal["langgraph", "runtime", "backend", "artifact", "benchmark"]
    name: str
    graph_node: str | None = None
    graph_step: int | None = None
    runtime_task_id: str | None = None
    attempt_id: str | None = None
    agent_name: str | None = None
    worker_pid: int | None = None
    backend_pid: int | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class RunEventBus:
    def __init__(self, run_id: str, thread_id: str, execution_mode: str, events_path: str | Path | None = None):
        self.run_id = run_id
        self.thread_id = thread_id
        self.execution_mode = execution_mode
        self.events_path = Path(events_path) if events_path else None
        self._events: list[RunEvent] = []
        self._next_id = 1
        if self.events_path:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        layer: Literal["langgraph", "runtime", "backend", "artifact", "benchmark"],
        name: str,
        **kwargs: Any,
    ) -> RunEvent:
        event = RunEvent(
            event_id=self._next_id,
            timestamp=time.time(),
            run_id=self.run_id,
            thread_id=self.thread_id,
            execution_mode=self.execution_mode,
            layer=layer,
            name=name,
            **kwargs,
        )
        self._next_id += 1
        self._events.append(event)
        if self.events_path:
            with self.events_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.model_dump(), ensure_ascii=False) + "\n")
        return event

    def list_after(self, after_id: int = 0) -> list[RunEvent]:
        return [event for event in self._events if event.event_id > after_id]
