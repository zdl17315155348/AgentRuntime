from __future__ import annotations

from dataclasses import dataclass

from aruntime.llm.gateway import LLMGateway

from applications.incident_repair.planning import DirectDeepSeekLLMAdapter, LocalRepositoryInspector, PlannerPipeline


@dataclass
class DirectDeepSeekExecutor:
    llm_gateway: LLMGateway | None = None
    max_inspection_files: int = 6

    async def execute_plan(self, system_prompt: str, goal: str, source_repo: str, available_roles: list[str]) -> dict:
        gateway = self.llm_gateway or LLMGateway(backend="deepseek")
        pipeline = PlannerPipeline()
        result = await pipeline.execute(
            goal=goal,
            system_prompt=system_prompt,
            inspector=LocalRepositoryInspector(source_repo),
            llm=DirectDeepSeekLLMAdapter(gateway),
            available_roles=available_roles,
            max_inspection_files=self.max_inspection_files,
        )
        return {
            "version": result.plan.version,
            "summary": result.plan.summary,
            "inspection": result.inspection.model_dump(mode="json"),
            "tasks": [task.model_dump(mode="json") for task in result.plan.tasks],
        }
