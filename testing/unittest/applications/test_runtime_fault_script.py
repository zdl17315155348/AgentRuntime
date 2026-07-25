from __future__ import annotations

import asyncio

from aruntime.core.models import AgentSpec, AgentStatus, TaskSpec, TaskStatus
from aruntime.daemon import main as daemon_main
from aruntime.daemon.store import SQLiteStateStore
from scripts.run_real_runtime_fault import _fault_evidence, _task_backend_pid, _wait_and_inject
from aruntime.daemon.main import _backend_trace_name_and_detail


def test_fault_evidence_requires_distinct_fallback_attempts():
    events = [
        {"name": "backend_started"},
        {"name": "worker.lost"},
        {"name": "lease.reclaim"},
        {"name": "task.fallback"},
    ]
    runtime_summary = {
        "faults": {"worker_lost": 1},
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

    assert evidence["worker_lost"] == 2
    assert evidence["fallback_created"] == 1
    assert evidence["same_task_id"] is True
    assert evidence["attempt_id_changed"] is True
    assert evidence["worker_pid_changed"] is True
    assert evidence["codex_pid_changed"] is True
    assert evidence["agent_switched_to_coder_b"] is True
    assert evidence["new_worktree"] is True
    assert evidence["recovery_context_loaded"] is True
    assert evidence["leases_active"] == 0


def test_fault_evidence_uses_failed_coder_fallback_pair_for_identity():
    runtime_summary = {
        "faults": {"worker_lost": 1},
        "resource": {"leases": []},
        "attempts": [
            {"attempt_id": "task-a:attempt:1", "agent_name": "coder_a", "status": "FAILED", "worker_pid": 1, "backend_pid": 10, "workspace_path": "/w/a"},
            {"attempt_id": "task-a:attempt:2", "agent_name": "coder_b", "status": "SUCCESS", "worker_pid": 2, "backend_pid": 11, "workspace_path": "/w/b", "recovery_context_id": "ctx"},
            {"attempt_id": "task-b:attempt:1", "agent_name": "coder_a", "status": "SUCCESS", "worker_pid": 3, "backend_pid": 12, "workspace_path": "/w/c"},
        ],
    }

    evidence = _fault_evidence([{"name": "task.fallback"}], runtime_summary)

    assert evidence["same_task_id"] is True
    assert evidence["agent_switched_to_coder_b"] is True
    assert evidence["attempt_success"] == 2


def test_backend_event_trace_uses_nested_backend_event_name():
    name, detail = _backend_trace_name_and_detail(
        "coder_a",
        {
            "type": "backend_event",
            "task_id": "task-1",
            "attempt_id": "task-1:attempt:1",
            "event": {"name": "backend.started", "backend_pid": 123},
        },
    )

    assert name == "backend.started"
    assert detail["agent_name"] == "coder_a"
    assert detail["backend_pid"] == 123
    assert detail["task_id"] == "task-1"


def test_store_lists_tasks_by_root_task_id(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTD_STATE_DB", str(tmp_path / "state.db"))
    store = SQLiteStateStore()
    try:
        task = TaskSpec(agent_name="coder_a", task_input={}, root_task_id="run-1", status=TaskStatus.READY)
        store.save_task(task)

        rows = store.list_tasks_for_run("run-1")

        assert [row["task_id"] for row in rows] == [task.task_id]
    finally:
        store.close()


def test_task_backend_pid_detects_running_coder_a():
    assert _task_backend_pid(
        {
            "task_id": "task-1",
            "agent_name": "coder_a",
            "status": "RUNNING",
            "attempts": [{"attempt_id": "task-1:attempt:1", "backend_pid": 123}],
        }
    ) == 123
    assert _task_backend_pid({"agent_name": "coder_a", "status": "SUCCESS", "attempts": [{"backend_pid": 123}]}) is None
    assert _task_backend_pid({"agent_name": "coder_b", "status": "RUNNING", "attempts": [{"backend_pid": 123}]}) is None


def test_fault_injector_ignores_partial_runtime_summary(monkeypatch):
    calls = {"events": 0, "injected": 0}

    class FakeClient:
        def __init__(self, base_url):
            self.base_url = base_url

        def inject_worker_sigkill(self, agent_name):
            calls["injected"] += 1
            return {"injected": True, "agent_name": agent_name}

    def fake_tasks(base_url, run_id):
        return [{"task_id": "task-1", "agent_name": "coder_a"}]

    def fake_events(base_url, run_id, after_id):
        calls["events"] += 1
        if calls["events"] == 1:
            return [{"id": 1, "task_id": "task-1", "name": "task.created", "data": {"agent_name": "coder_a"}}]
        return [{"id": 2, "task_id": "task-1", "name": "backend.started", "data": {"agent_name": "coder_a"}}]

    monkeypatch.setattr("scripts.run_real_runtime_fault.AgentRuntimeClient", FakeClient)
    monkeypatch.setattr("scripts.run_real_runtime_fault._run_tasks", fake_tasks)
    monkeypatch.setattr("scripts.run_real_runtime_fault._run_events", fake_events)

    done = asyncio.Event()

    async def finish_after_injection():
        while calls["injected"] == 0:
            await asyncio.sleep(0)
        done.set()

    async def run_test():
        waiter = asyncio.create_task(finish_after_injection())
        result = await _wait_and_inject("http://agentd", "run-1", 3, done)
        await waiter
        return result

    result = asyncio.run(run_test())

    assert result["injection"]["injected"] is True
    assert calls["events"] >= 2


def test_debug_sigkill_worker_prefers_backend_pid(monkeypatch):
    killed = {}

    def fake_kill(pid, sig):
        killed["pid"] = pid
        killed["sig"] = sig

    agent = AgentSpec(agent_name="coder_a", role="Coder")
    task = TaskSpec(agent_name="coder_a", task_input={}, root_task_id="run-1", status=TaskStatus.RUNNING)
    task.create_attempt("coder_a", worker_pid=11).backend_pid = 42
    daemon_main.agents.clear()
    daemon_main.tasks.clear()
    daemon_main.agent_workers.clear()
    daemon_main.agents["coder_a"] = agent
    daemon_main.tasks[task.task_id] = task
    daemon_main.agent_workers["coder_a"] = type("P", (), {"pid": 11, "poll": lambda self=None: None})()
    agent.current_task_id = task.task_id

    monkeypatch.setenv("AGENTD_ENABLE_FAULT_INJECTION", "true")
    monkeypatch.setattr(daemon_main.os, "kill", fake_kill)

    result = asyncio.run(daemon_main.debug_sigkill_worker("coder_a"))

    assert result["pid"] == 42
    assert result["worker_pid"] == 11
    assert killed == {"pid": 42, "sig": 9}
