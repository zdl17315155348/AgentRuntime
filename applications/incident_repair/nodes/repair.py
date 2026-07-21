from __future__ import annotations

from applications.incident_repair.execution.base import AgentExecutionRequest
from applications.incident_repair.nodes.common import context_from_runtime, execution_record_from_result, load_prompt
from applications.incident_repair.routing import build_idempotency_key


async def repair_node(state: dict, runtime):
    context = context_from_runtime(runtime)
    repair_round = int(state.get("repair_round", 0)) + 1
    timeout_s = int(context.run_config.task_timeout_s)
    request = AgentExecutionRequest(
        run_id=state["run_id"],
        thread_id=state["thread_id"],
        graph_node="repair",
        graph_step=10 + repair_round,
        role="repair",
        backend="codex_cli",
        goal=state["user_request"],
        system_prompt=load_prompt("repair.md"),
        task_input={"test_summary": state.get("test_summary"), "patch_refs": state.get("patch_refs", [])},
        source_repo=state["source_repo"],
        base_commit=state.get("integrated_commit") or state["base_commit"],
        timeout_s=timeout_s,
        idempotency_key=build_idempotency_key(state["thread_id"], "repair", 10 + repair_round, "root"),
        resource_request={"cpu_cores": 1, "memory_mb": 1024, "llm_slots": 1},
    )
    result = await context.provider.execute(request)
    if result.status != "SUCCESS":
        return {"workflow_status": "FAILED", "error": result.error_message or "repair failed", "repair_round": repair_round}
    if not result.patch_ref:
        return {"workflow_status": "FAILED", "error": "repair produced no patch", "repair_round": repair_round}
    return {
        "repair_round": repair_round,
        "patch_refs": [result.patch_ref] if result.patch_ref else [],
        "all_patch_refs": [result.patch_ref] if result.patch_ref else [],
        "pending_patch_refs": [result.patch_ref] if result.patch_ref else [],
        "runtime_task_ids": [result.runtime_task_id] if result.runtime_task_id else [],
        "execution_records": [execution_record_from_result(request, result, context.provider.mode)],
    }
