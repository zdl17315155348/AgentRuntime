from __future__ import annotations

from applications.incident_repair.execution.base import AgentExecutionRequest
from applications.incident_repair.nodes.common import context_from_runtime, execution_record_from_result, load_prompt
from applications.incident_repair.routing import build_idempotency_key


class CoderNodeError(Exception):
    pass


async def coder_node(state: dict, runtime):
    context = context_from_runtime(runtime)
    task = state["active_coder_task"]
    request = AgentExecutionRequest(
        run_id=state["run_id"],
        thread_id=state["thread_id"],
        graph_node="coder",
        graph_step=1,
        role="coder",
        backend="codex_cli",
        goal=task["goal"],
        system_prompt=load_prompt("coder.md"),
        task_input={"local_id": task["local_id"]},
        source_repo=state["source_repo"],
        base_commit=state["base_commit"],
        timeout_s=300,
        idempotency_key=build_idempotency_key(state["thread_id"], "coder", 1, task["local_id"]),
        resource_request={"cpu_cores": 1, "memory_mb": 1024, "llm_slots": 1},
    )
    result = await context.provider.execute(request)
    if result.status != "SUCCESS":
        raise CoderNodeError(result.error_message or "coder failed")
    if not result.patch_ref:
        raise CoderNodeError("coder produced no patch")
    return {
        "patch_refs": [result.patch_ref] if result.patch_ref else [],
        "all_patch_refs": [result.patch_ref] if result.patch_ref else [],
        "pending_patch_refs": [result.patch_ref] if result.patch_ref else [],
        "runtime_task_ids": [result.runtime_task_id] if result.runtime_task_id else [],
        "execution_records": [execution_record_from_result(request, result, context.provider.mode)],
    }
