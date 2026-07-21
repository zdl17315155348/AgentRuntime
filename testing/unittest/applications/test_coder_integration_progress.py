from __future__ import annotations

from types import SimpleNamespace

import pytest

from applications.incident_repair.config import ExecutionMode, GraphRuntimeContext, IncidentRunConfig
from applications.incident_repair.nodes.integrate_coder import integrate_coder_node
from applications.incident_repair.nodes.integrate_repair import integrate_repair_node


class _Integration:
    def __init__(self, status: str = "SUCCESS"):
        self.status = status

    def integrate(self, source_repo, base_commit, patch_refs, run_id, repair_round):
        artifact = str(patch_refs[0].get("artifact_id") or "patch")
        return SimpleNamespace(
            status=self.status,
            workspace_path=source_repo,
            base_commit=base_commit,
            integrated_commit=f"{base_commit}-{artifact}" if self.status == "SUCCESS" else None,
            applied_artifact_ids=[artifact],
            changed_files=list(patch_refs[0].get("changed_files", [])),
            conflict_files=["app.py"] if self.status != "SUCCESS" else [],
            error=None if self.status == "SUCCESS" else "conflict",
        )


def _context(service: _Integration) -> GraphRuntimeContext:
    return GraphRuntimeContext(
        provider=None,
        run_config=IncidentRunConfig(
            execution_mode=ExecutionMode.DIRECT,
            run_id="run",
            thread_id="thread",
            source_repo="/repo",
            base_commit="base0",
        ),
        event_bus=None,
        integration_service=service,
    )


def _state() -> dict:
    return {
        "run_id": "run",
        "source_repo": "/repo",
        "base_commit": "base0",
        "integrated_commit": None,
        "repair_round": 0,
        "completed_coder_task_ids": [],
        "active_coder_task": {"local_id": "a", "role": "coder", "goal": "fix", "dependencies": []},
        "pending_patch_refs": [
            {
                "task_local_id": "a",
                "artifact_id": "a1",
                "patch_path": "/tmp/a.patch",
                "sha256": "sha",
                "changed_files": ["app.py"],
            }
        ],
    }


@pytest.mark.anyio
async def test_coder_marked_complete_only_after_successful_integration():
    update = await integrate_coder_node(_state(), _context(_Integration()))

    assert update["integrated_commit"] == "base0-a1"
    assert update["completed_coder_task_ids"] == ["a"]
    assert update["active_coder_task"] is None
    assert update["pending_patch_refs"] == []
    assert update["coder_integration_history"] == [
        {"task_id": "a", "base_commit": "base0", "integrated_commit": "base0-a1", "changed_files": ["app.py"]}
    ]


@pytest.mark.anyio
async def test_integration_failure_does_not_mark_coder_complete():
    update = await integrate_coder_node(_state(), _context(_Integration(status="CONFLICT")))

    assert update["workflow_status"] == "FAILED"
    assert "completed_coder_task_ids" not in update
    assert "active_coder_task" not in update


@pytest.mark.anyio
async def test_repair_integration_does_not_modify_completed_coders():
    state = _state()
    state["completed_coder_task_ids"] = ["a"]
    update = await integrate_repair_node(state, _context(_Integration()))

    assert update["integrated_commit"] == "base0-a1"
    assert "completed_coder_task_ids" not in update


@pytest.mark.anyio
async def test_coder_integration_rejects_codex_private_files():
    state = _state()
    state["pending_patch_refs"][0]["changed_files"] = [".codex-final.json"]
    update = await integrate_coder_node(state, _context(_Integration()))

    assert update["workflow_status"] == "FAILED"
    assert update["error"] == "codex private files leaked into patch: ['.codex-final.json']"
