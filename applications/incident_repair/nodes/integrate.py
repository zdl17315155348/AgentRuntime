from __future__ import annotations

from applications.incident_repair.nodes.common import context_from_runtime


async def integrate_node(state: dict, runtime):
    context = context_from_runtime(runtime)
    patch_refs = state.get("pending_patch_refs") or []
    if not patch_refs:
        return {"workflow_status": "FAILED", "error": "no pending patches to integrate"}
    service = context.integration_service
    result = service.integrate(
        source_repo=state["source_repo"],
        base_commit=state.get("integrated_commit") or state["base_commit"],
        patch_refs=patch_refs,
        run_id=state["run_id"],
        repair_round=int(state.get("repair_round", 0)),
    )
    integration_result = {
        "status": result.status,
        "workspace_path": result.workspace_path,
        "base_commit": result.base_commit,
        "integrated_commit": result.integrated_commit,
        "applied_artifact_ids": result.applied_artifact_ids,
        "changed_files": result.changed_files,
        "conflict_files": result.conflict_files,
        "error": result.error,
    }
    if result.status != "SUCCESS":
        return {"workflow_status": "FAILED", "error": result.error, "integration_result": integration_result}
    return {
        "integrated_commit": result.integrated_commit,
        "integration_result": integration_result,
        "pending_patch_refs": [],
    }
