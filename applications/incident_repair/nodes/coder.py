from __future__ import annotations

from applications.incident_repair.execution.base import AgentExecutionRequest
from applications.incident_repair.nodes.common import context_from_runtime, execution_record_from_result, load_prompt
from applications.incident_repair.routing import build_idempotency_key


class CoderNodeError(Exception):
    pass


async def coder_node(state: dict, runtime):
    context = context_from_runtime(runtime)
    task = state["active_coder_task"]
    timeout_s = int(context.run_config.task_timeout_s)
    execution_base_commit = state.get("integrated_commit") or state["base_commit"]
    coder_step = int(state.get("coder_step", 1))
    request = AgentExecutionRequest(
        run_id=state["run_id"],
        thread_id=state["thread_id"],
        graph_node="coder",
        graph_step=coder_step,
        role="coder",
        backend="codex_cli",
        goal=task["goal"],
        system_prompt=load_prompt("coder.md"),
        task_input={
            "local_id": task["local_id"],
            "dependencies": task.get("dependencies", []),
            "base_commit": execution_base_commit,
            "coder_step": coder_step,
        },
        source_repo=state["source_repo"],
        base_commit=execution_base_commit,
        timeout_s=timeout_s,
        idempotency_key=build_idempotency_key(
            state["thread_id"],
            "coder",
            coder_step,
            f"{task['local_id']}:{execution_base_commit}",
        ),
        resource_request={"cpu_cores": 1, "memory_mb": 1024, "llm_slots": 1},
    )
    result = await context.provider.execute(request)
    if result.status != "SUCCESS":
        return {
            "workflow_status": "FAILED",
            "error": result.error_message or "coder failed",
            "runtime_task_ids": [result.runtime_task_id] if result.runtime_task_id else [],
            "execution_records": [execution_record_from_result(request, result, context.provider.mode)],
        }
    if not result.patch_ref:
        return {
            "workflow_status": "FAILED",
            "error": "coder produced no patch",
            "runtime_task_ids": [result.runtime_task_id] if result.runtime_task_id else [],
            "execution_records": [execution_record_from_result(request, result, context.provider.mode)],
        }
    return {
        "patch_refs": [result.patch_ref] if result.patch_ref else [],
        "all_patch_refs": [result.patch_ref] if result.patch_ref else [],
        "pending_patch_refs": [result.patch_ref] if result.patch_ref else [],
        "runtime_task_ids": [result.runtime_task_id] if result.runtime_task_id else [],
        "execution_records": [execution_record_from_result(request, result, context.provider.mode)],
    }
