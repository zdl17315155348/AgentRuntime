from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from aruntime.planner.models import InspectionRequest, PlanSpec
from aruntime.planner.parser import load_json_object, normalize_inspection_payload, normalize_plan_payload
from aruntime.planner.prompt_builder import build_inspection_prompt, build_plan_prompt
from aruntime.planner.validator import validate_plan

from .llm import PlannerLLM
from .repository import RepositoryInspector


@dataclass
class PlannerPipelineResult:
    inspection: InspectionRequest
    plan: PlanSpec
    repo_tree: list[str]


class PlannerPipeline:
    async def execute(
        self,
        goal: str,
        system_prompt: str,
        inspector: RepositoryInspector,
        llm: PlannerLLM,
        available_roles: list[str],
        max_inspection_files: int = 6,
    ) -> PlannerPipelineResult:
        repo_tree = await inspector.repo_scan()
        inspection_prompt = build_inspection_prompt(goal, repo_tree[:200], "", available_roles, {"max_files": max_inspection_files, "max_searches": 4})
        inspection = await _complete_json_model(
            llm,
            system_prompt,
            inspection_prompt,
            lambda output: InspectionRequest(**normalize_inspection_payload(load_json_object(output))),
        )
        if not inspection.files and not inspection.searches:
            inspection = InspectionRequest(files=_fallback_inspection_files(repo_tree, max_inspection_files), searches=[], summary="fallback from repo_scan")
        inspected: dict[str, Any] = {"files": {}, "searches": []}
        for rel in inspection.files[:max_inspection_files]:
            inspected["files"][rel] = await inspector.read_file(rel)
        for search in inspection.searches[:4]:
            inspected["searches"].append({"query": search.query, "path": search.path, "matches": await inspector.search_code(search.query, search.path)})
        plan_prompt = build_plan_prompt(goal, inspected, available_roles)
        plan = await _complete_json_model(
            llm,
            system_prompt,
            plan_prompt,
            lambda output: PlanSpec(**normalize_plan_payload(load_json_object(output))),
        )
        validate_plan(plan)
        return PlannerPipelineResult(inspection=inspection, plan=plan, repo_tree=repo_tree)


def _fallback_inspection_files(repo_tree: list[str], max_files: int) -> list[str]:
    preferred = ("app/auth.py", "app/orders.py", "app/models.py", "app/main.py", "tests/test_auth.py", "tests/test_orders.py")
    files = [path for path in preferred if path in repo_tree]
    for path in repo_tree:
        if len(files) >= max_files:
            break
        if path in files or not path.endswith(".py"):
            continue
        if path.startswith("app/") or path.startswith("tests/"):
            files.append(path)
    return files[:max_files]


async def _complete_json_model(llm: PlannerLLM, system_prompt: str, prompt: str, parse):
    last_error: Exception | None = None
    current_prompt = prompt
    for _ in range(4):
        result = await llm.complete(system_prompt, current_prompt)
        try:
            return parse(result.output)
        except (ValueError, ValidationError) as exc:
            last_error = exc
            current_prompt = (
                prompt
                + "\n\nPrevious response was invalid JSON: "
                + str(exc)
                + "\nReturn one complete JSON object only. Do not truncate strings."
            )
    if last_error is not None:
        raise last_error
    raise ValueError("empty planner response")
