from __future__ import annotations

from scripts.run_real_runtime_fault import _fault_evidence


def test_fault_evidence_requires_distinct_fallback_attempts():
    events = [
        {"name": "backend_started"},
        {"name": "worker.lost"},
        {"name": "lease.reclaim"},
        {"name": "task.fallback"},
    ]
    runtime_summary = {
        "resource": {"leases": []},
        "attempts": [
            {
                "task_id": "task-1",
                "attempt_id": "task-1:attempt:1",
                "agent_name": "coder_a",
                "status": "FAILED",
                "worker_pid": 100,
                "backend_pid": 200,
                "workspace_path": "/w/a",
            },
            {
                "task_id": "task-1",
                "attempt_id": "task-1:attempt:2",
                "agent_name": "coder_b",
                "status": "SUCCESS",
                "worker_pid": 101,
                "backend_pid": 201,
                "workspace_path": "/w/b",
                "recovery_context_id": "ctx",
            },
        ],
    }

    evidence = _fault_evidence(events, runtime_summary)

    assert evidence["worker_lost"] == 1
    assert evidence["fallback_created"] == 1
    assert evidence["same_task_id"] is True
    assert evidence["attempt_id_changed"] is True
    assert evidence["worker_pid_changed"] is True
    assert evidence["codex_pid_changed"] is True
    assert evidence["agent_switched_to_coder_b"] is True
    assert evidence["new_worktree"] is True
    assert evidence["recovery_context_loaded"] is True
    assert evidence["leases_active"] == 0
