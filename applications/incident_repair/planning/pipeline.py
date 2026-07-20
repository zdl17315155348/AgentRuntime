from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
        first = await llm.complete(system_prompt, inspection_prompt)
        inspection = InspectionRequest(**normalize_inspection_payload(load_json_object(first.output)))
        if not inspection.files and not inspection.searches:
            inspection = InspectionRequest(files=_fallback_inspection_files(repo_tree, max_inspection_files), searches=[], summary="fallback from repo_scan")
        inspected: dict[str, Any] = {"files": {}, "searches": []}
        for rel in inspection.files[:max_inspection_files]:
            inspected["files"][rel] = await inspector.read_file(rel)
        for search in inspection.searches[:4]:
            inspected["searches"].append({"query": search.query, "path": search.path, "matches": await inspector.search_code(search.query, search.path)})
        plan_prompt = build_plan_prompt(goal, inspected, available_roles)
        second = await llm.complete(system_prompt, plan_prompt)
        plan = PlanSpec(**normalize_plan_payload(load_json_object(second.output)))
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
