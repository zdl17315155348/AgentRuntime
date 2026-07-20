from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from applications.incident_repair.execution.base import AgentExecutionRequest, AgentExecutionResult, ExecutionMetrics, ExecutionProvider


class ReplayExecutionProvider(ExecutionProvider):
    def __init__(self, manifest_path: str | Path | None = None):
        self.manifest_path = Path(manifest_path) if manifest_path else None

    @property
    def mode(self) -> str:
        return "replay"

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        metrics = ExecutionMetrics(submit_started_at=0, execution_started_at=0, execution_finished_at=0)
        return AgentExecutionResult(status="SUCCESS", output="REPLAY", structured_result=self._load_manifest(), metrics=metrics)

    async def cancel_run(self, run_id: str) -> None:
        return None

    async def inject_fault(self, run_id: str, target: dict[str, Any]) -> dict[str, Any]:
        return {"run_id": run_id, "mode": "replay", "injected": False}

    async def get_execution_snapshot(self, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id, "mode": "replay", "manifest": self._load_manifest()}

    def _load_manifest(self) -> dict[str, Any]:
        if self.manifest_path and self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        return {"source": "recorded", "events_file": "unified_events.jsonl", "speed": 1.0}
