from __future__ import annotations

import subprocess

from applications.incident_repair.execution.base import AgentExecutionRequest
from applications.incident_repair.nodes.common import context_from_runtime
from applications.incident_repair.routing import build_idempotency_key


async def integrate_node(state: dict, runtime):
    context = context_from_runtime(runtime)
    provider = context.provider
    if provider.mode == "runtime":
        result = await provider.execute(
            AgentExecutionRequest(
                run_id=state["run_id"],
                thread_id=state["thread_id"],
                graph_node="integrate",
                graph_step=2,
                role="integrator",
                backend="runtime_internal",
                goal="apply patch artifacts in stable order",
                task_input={"patch_refs": state.get("patch_refs", [])},
                source_repo=state["source_repo"],
                base_commit=state["base_commit"],
                timeout_s=120,
                idempotency_key=build_idempotency_key(state["thread_id"], "integrate", 2, "root"),
            )
        )
        return {"integrated_commit": result.structured_result.get("commit") or state["base_commit"]}
    commit = subprocess.run(
        ["git", "-C", state["source_repo"], "rev-parse", state["base_commit"]],
        capture_output=True,
        text=True,
        check=False,
    )
    if commit.returncode != 0:
        return {"workflow_status": "FAILED", "error": commit.stderr or commit.stdout}
    return {"integrated_commit": commit.stdout.strip()}
