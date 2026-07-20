from __future__ import annotations

import json

import pytest

from aruntime.llm.gateway import LLMResult
from applications.incident_repair.planning import LocalRepositoryInspector, PlannerPipeline


class _LLM:
    def __init__(self):
        self.calls = 0

    async def complete(self, system_prompt: str, prompt: str) -> LLMResult:
        self.calls += 1
        if self.calls == 1:
            output = json.dumps({"files": ["app/auth.py"], "searches": [{"query": "bug", "path": "."}], "summary": "inspect"})
        else:
            output = json.dumps(
                {
                    "version": "1.0",
                    "summary": "plan",
                    "tasks": [
                        {"local_id": "fix", "role": "coder", "goal": "fix bug"},
                        {"local_id": "test", "role": "tester", "goal": "run tests", "dependencies": ["fix"]},
                        {"local_id": "review", "role": "reviewer", "goal": "review", "dependencies": ["test"]},
                    ],
                }
            )
        return LLMResult(output=output, input_tokens=1, output_tokens=1, total_tokens=2, latency_ms=1)


@pytest.mark.anyio
async def test_shared_planner_pipeline_scans_reads_searches_and_validates_plan(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "auth.py").write_text("# bug\n", encoding="utf-8")

    result = await PlannerPipeline().execute(
        goal="fix bug",
        system_prompt="plan",
        inspector=LocalRepositoryInspector(str(tmp_path)),
        llm=_LLM(),
        available_roles=["coder", "tester", "reviewer"],
    )

    assert result.inspection.files == ["app/auth.py"]
    assert result.plan.tasks[0].role == "coder"
