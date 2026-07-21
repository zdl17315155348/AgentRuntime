from __future__ import annotations

from applications.incident_repair.nodes.integrate import _integrate_pending_patches


def _forbidden_patch_files(patch_refs: list[dict]) -> list[str]:
    forbidden: list[str] = []
    for patch in patch_refs:
        changed_files = patch.get("changed_files", [])
        forbidden.extend(
            path
            for path in changed_files
            if path.startswith(".codex-home") or path in {".codex-events.jsonl", ".codex-final.json"}
        )
    return forbidden


async def integrate_coder_node(state: dict, runtime):
    if state.get("workflow_status") == "FAILED":
        return {"active_coder_task": None}

    forbidden = _forbidden_patch_files(state.get("pending_patch_refs") or [])
    if forbidden:
        return {
            "workflow_status": "FAILED",
            "error": f"codex private files leaked into patch: {forbidden}",
        }

    integration_update = await _integrate_pending_patches(state, runtime)
    if integration_update.get("workflow_status") == "FAILED":
        return integration_update

    task = state["active_coder_task"]
    completed = set(state.get("completed_coder_task_ids", []))
    completed.add(task["local_id"])
    result = integration_update["integration_result"]
    return {
        **integration_update,
        "completed_coder_task_ids": sorted(completed),
        "active_coder_task": None,
        "coder_integration_history": [
            {
                "task_id": task["local_id"],
                "base_commit": result["base_commit"],
                "integrated_commit": result["integrated_commit"],
                "changed_files": result["changed_files"],
            }
        ],
    }
