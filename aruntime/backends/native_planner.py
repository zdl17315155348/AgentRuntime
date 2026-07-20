from __future__ import annotations

import json
from pathlib import Path

from aruntime.backends.base import BackendExecutionRequest, BackendExecutionResult, EmitEvent
from aruntime.backends.legacy_llm import LegacyLLMBackend
from aruntime.core.models import AgentBackendType
from aruntime.executor.task_executor import TaskExecutor
from aruntime.planner.models import InspectionRequest, PlanSpec
from aruntime.planner.parser import load_json_object, normalize_inspection_payload, normalize_plan_payload
from aruntime.planner.prompt_builder import build_inspection_prompt, build_plan_prompt
from aruntime.planner.validator import validate_plan
from aruntime.tools.base import ToolExecutionContext


class NativePlannerBackend(LegacyLLMBackend):
    def __init__(self, config, dependencies: dict):
        super().__init__(config, dependencies)
        self.executor = dependencies.get("executor")

    async def execute(self, request: BackendExecutionRequest, emit_event: EmitEvent) -> BackendExecutionResult:
        executor: TaskExecutor | None = getattr(self, "executor", None)
        if executor is None:
            executor = self.__dict__.get("executor")
        executor = executor or self._dependencies_executor()
        if executor is None:
            return await super().execute(request, emit_event)
        if not request.workspace.workspace_path:
            return BackendExecutionResult(status="FAILED", error="workspace_path is required", backend_type=AgentBackendType.NATIVE_PLANNER.value)

        context = ToolExecutionContext(
            workspace_root=Path(request.workspace.workspace_path).resolve(),
            allowed_roots=[Path(request.workspace.workspace_path).resolve()],
            timeout_s=request.timeout_s,
            max_output_bytes=256 * 1024,
        )
        scan = await executor.execute_tool("repo_scan", {}, context)
        if not scan.ok:
            return BackendExecutionResult(status="FAILED", error=scan.error or "repo_scan failed", backend_type=AgentBackendType.NATIVE_PLANNER.value)
        repo_tree = scan.output if isinstance(scan.output, list) else []
        readme_summary = ""
        readme = Path(request.workspace.workspace_path) / "README.md"
        if readme.exists():
            readme_summary = readme.read_text(encoding="utf-8", errors="replace")[:4096]
        roles = request.runtime_context.get("available_roles", ["coder", "tester", "reviewer"])
        goal = str(request.task_input.get("request") or request.user_message)
        await emit_event({"name": "planner.repo_scan", "files": len(repo_tree)})

        inspection_prompt = build_inspection_prompt(
            goal,
            repo_tree[:200],
            readme_summary,
            roles if isinstance(roles, list) else ["coder", "tester", "reviewer"],
            {"max_files": self.config.max_inspection_files, "max_searches": 4},
        )
        first = self.llm_gateway.chat_with_stats(request.system_prompt, inspection_prompt)
        try:
            inspection = InspectionRequest(**normalize_inspection_payload(load_json_object(first.output)))
            _validate_inspection(inspection, self.config.max_inspection_files)
        except Exception as exc:
            return BackendExecutionResult(
                status="FAILED",
                error=f"invalid inspection request: {exc}",
                backend_type=AgentBackendType.NATIVE_PLANNER.value,
                usage=first.to_dict(),
            )
        if not inspection.files and not inspection.searches:
            inspection = InspectionRequest(files=_fallback_inspection_files(repo_tree, self.config.max_inspection_files), searches=[], summary="fallback from repo_scan")

        inspected: dict[str, object] = {"files": {}, "searches": []}
        total_bytes = 0
        for rel in inspection.files[: self.config.max_inspection_files]:
            path = _safe_relative(rel)
            tool_result = await executor.execute_tool("read_file", {"path": path}, context)
            if tool_result.ok:
                text = str(tool_result.output)[: 64 * 1024]
                total_bytes += len(text.encode("utf-8"))
                if total_bytes <= 256 * 1024:
                    inspected["files"][path] = text
        for search in inspection.searches[:4]:
            path = _safe_relative(search.path or ".")
            tool_result = await executor.execute_tool("search_code", {"needle": search.query, "path": path}, context)
            inspected["searches"].append({"query": search.query, "path": path, "matches": tool_result.output if tool_result.ok else []})
        await emit_event({"name": "planner.inspection.completed", "files": len(inspected["files"]), "searches": len(inspected["searches"])})

        plan_prompt = build_plan_prompt(goal, inspected, roles if isinstance(roles, list) else ["coder", "tester", "reviewer"])
        second = self.llm_gateway.chat_with_stats(request.system_prompt, plan_prompt)
        usage = first.to_dict()
        second_usage = second.to_dict()
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            usage[key] = int(usage.get(key) or 0) + int(second_usage.get(key) or 0)
        try:
            plan = PlanSpec(**normalize_plan_payload(load_json_object(second.output)))
            validate_plan(plan)
        except Exception as exc:
            return BackendExecutionResult(
                status="FAILED",
                error=f"invalid plan: {exc}",
                backend_type=AgentBackendType.NATIVE_PLANNER.value,
                usage=usage,
            )
        return BackendExecutionResult(
            status="SUCCESS",
            output=json.dumps({"inspection": inspection.model_dump(mode="json"), "plan": plan.model_dump(mode="json")}, ensure_ascii=False),
            backend_type=AgentBackendType.NATIVE_PLANNER.value,
            usage=usage,
        )

    def _dependencies_executor(self):
        return getattr(self, "executor", None)


def _safe_relative(path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"unsafe path: {path}")
    return str(candidate)


def _validate_inspection(inspection: InspectionRequest, max_files: int) -> None:
    if len(inspection.files) > max_files:
        raise ValueError("too many files")
    if len(inspection.searches) > 4:
        raise ValueError("too many searches")
    for path in inspection.files:
        _safe_relative(path)
    for search in inspection.searches:
        _safe_relative(search.path or ".")


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
