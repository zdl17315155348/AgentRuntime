from __future__ import annotations

import asyncio
import json

import pytest

from aruntime.daemon.main import CreateDemoRunRequest, cancel_demo_run, create_demo_run, get_demo_events, get_demo_replay, get_demo_run, get_demo_runtime_tasks, stream_demo_events
from aruntime.core.models import AgentBackendConfig, AgentBackendType, AgentSpec, AgentStatus, TaskSpec, TaskStatus
from aruntime.daemon.store import SQLiteStateStore
from aruntime.workspace import ArtifactStore, WorkspaceManager


@pytest.mark.anyio
async def test_demo_run_api_creates_bundle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    resp = await create_demo_run(
        CreateDemoRunRequest(
            execution_mode="replay",
            task_case="incident_repair_v1",
            user_request="fix auth",
            source_repo="/data1/projects/agent-runtime-os",
            base_commit="HEAD",
        )
    )

    run_id = resp["run_id"]
    await asyncio.sleep(0)
    assert (await get_demo_run(run_id))["run_id"] == run_id
    events = (await get_demo_events(run_id))["events"]
    assert events[0]["name"] == "graph.run.started"
    replay = await get_demo_replay(run_id)
    assert replay["source"] == "recorded"
    stream = await stream_demo_events(run_id)
    assert stream.media_type == "text/event-stream"


@pytest.mark.anyio
async def test_create_demo_run_registers_demo_agents(tmp_path, monkeypatch):
    import aruntime.daemon.main as daemon_main

    monkeypatch.chdir(tmp_path)
    daemon_main.agents.clear()
    daemon_main.agent_controls.clear()
    daemon_main.fault_states.clear()
    daemon_main.agent_workers.clear()
    daemon_main.demo_run_tasks.clear()
    daemon_main.demo_runs.clear()
    started = []
    monkeypatch.setattr(daemon_main, "_start_worker", lambda agent_name: started.append(agent_name))

    await create_demo_run(
        CreateDemoRunRequest(
            execution_mode="replay",
            task_case="incident_repair_v1",
            user_request="fix auth",
            source_repo="/data1/projects/agent-runtime-os",
            base_commit="HEAD",
        )
    )

    assert {"architect", "coder_a", "coder_b", "tester", "repair", "reviewer"} <= set(daemon_main.agents.keys())
    assert all(daemon_main.agents[name].status.value == "READY" for name in {"architect", "coder_a", "coder_b", "tester", "repair", "reviewer"})
    assert {"architect", "coder_a", "coder_b", "tester", "repair", "reviewer"} <= set(started)


@pytest.mark.anyio
async def test_create_demo_run_recovers_preexisting_created_demo_agents(tmp_path, monkeypatch):
    import aruntime.daemon.main as daemon_main

    monkeypatch.chdir(tmp_path)
    daemon_main.agents.clear()
    daemon_main.agent_controls.clear()
    daemon_main.fault_states.clear()
    daemon_main.agent_workers.clear()
    daemon_main.demo_run_tasks.clear()
    daemon_main.demo_runs.clear()
    started = []
    monkeypatch.setattr(daemon_main, "_start_worker", lambda agent_name: started.append(agent_name))
    monkeypatch.setattr(daemon_main, "_stop_worker", lambda agent_name: None)

    daemon_main.agents["architect"] = AgentSpec(agent_name="architect", role="规划者", status=AgentStatus.CREATED)

    await create_demo_run(
        CreateDemoRunRequest(
            execution_mode="replay",
            task_case="incident_repair_v1",
            user_request="fix auth",
            source_repo="/data1/projects/agent-runtime-os",
            base_commit="HEAD",
        )
    )

    assert daemon_main.agents["architect"].status == AgentStatus.READY
    assert "architect" in started


@pytest.mark.anyio
async def test_demo_events_returns_empty_before_event_file_exists(tmp_path, monkeypatch):
    import aruntime.daemon.main as daemon_main

    monkeypatch.chdir(tmp_path)
    run_id = "run_without_events"
    daemon_main.demo_run_service.store.run_dir(run_id).mkdir(parents=True, exist_ok=True)

    assert await get_demo_events(run_id) == {"events": []}


@pytest.mark.anyio
async def test_demo_run_marks_orphan_created_run_interrupted(tmp_path, monkeypatch):
    import aruntime.daemon.main as daemon_main

    monkeypatch.chdir(tmp_path)
    run_id = "run_orphan"
    run_dir = daemon_main.demo_run_service.store.run_dir(run_id)
    (run_dir / "summary.json").write_text(json.dumps({"run_id": run_id, "status": "CREATED", "started_at": 1.0}), encoding="utf-8")
    (run_dir / "graph_state.json").write_text(json.dumps({"run_id": run_id, "workflow_status": "PENDING"}), encoding="utf-8")
    (run_dir / "unified_events.jsonl").write_text(json.dumps({"event_id": 1, "name": "graph.run.started"}) + "\n", encoding="utf-8")
    daemon_main.demo_run_tasks.pop(run_id, None)

    data = await get_demo_run(run_id)

    assert data["status"] == "INTERRUPTED"
    assert data["error"] == "demo run interrupted; agentd process stopped before completion"
    assert json.loads((run_dir / "graph_state.json").read_text(encoding="utf-8"))["workflow_status"] == "INTERRUPTED"


@pytest.mark.anyio
async def test_demo_run_merges_terminal_graph_state_into_stale_summary(tmp_path, monkeypatch):
    import aruntime.daemon.main as daemon_main

    monkeypatch.chdir(tmp_path)
    run_id = "run_stale_summary"
    run_dir = daemon_main.demo_run_service.store.run_dir(run_id)
    (run_dir / "summary.json").write_text(
        json.dumps({"run_id": run_id, "status": "CREATED", "started_at": 1.0, "result": {"review_approved": False}}),
        encoding="utf-8",
    )
    (run_dir / "graph_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "workflow_status": "SUCCESS",
                "test_summary": {"returncode": 0, "passed": 8, "failed": 0},
                "review_summary": {"approved": True},
            }
        ),
        encoding="utf-8",
    )

    data = await get_demo_run(run_id)

    assert data["status"] == "SUCCESS"
    assert data["result"]["pytest_returncode"] == 0
    assert data["result"]["tests_passed"] == 8
    assert data["result"]["review_approved"] is True
    assert json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))["status"] == "SUCCESS"


@pytest.mark.anyio
async def test_cancel_demo_run_deletes_persisted_run_after_restart(tmp_path, monkeypatch):
    import aruntime.daemon.main as daemon_main

    monkeypatch.chdir(tmp_path)
    run_id = "run_persisted"
    run_dir = daemon_main.demo_run_service.store.run_dir(run_id)
    (run_dir / "summary.json").write_text(json.dumps({"run_id": run_id, "status": "INTERRUPTED", "started_at": 1.0}), encoding="utf-8")
    daemon_main.demo_runs.pop(run_id, None)
    daemon_main.demo_run_tasks.pop(run_id, None)

    data = await cancel_demo_run(run_id)

    assert data["run_id"] == run_id
    assert data["status"] == "DELETED"
    assert not run_dir.exists()


@pytest.mark.anyio
async def test_cancel_demo_run_cancels_and_deletes_runtime_tasks(tmp_path, monkeypatch):
    import aruntime.daemon.main as daemon_main

    monkeypatch.chdir(tmp_path)
    store = SQLiteStateStore(str(tmp_path / "state.db"))
    workspace_manager = WorkspaceManager(workspace_root=str(tmp_path / "workspaces"))
    artifact_store = ArtifactStore(str(tmp_path / "artifacts"))
    monkeypatch.setattr(daemon_main, "state_store", store)
    monkeypatch.setattr(daemon_main, "workspace_manager", workspace_manager)
    monkeypatch.setattr(daemon_main, "artifact_store", artifact_store)
    run_id = "run_runtime_cancel"
    task = TaskSpec(agent_name="repair", task_input={}, root_task_id=run_id, status=TaskStatus.READY)
    daemon_main.tasks[task.task_id] = task
    store.save_task(task)
    run_dir = daemon_main.demo_run_service.store.run_dir(run_id)
    (run_dir / "summary.json").write_text(json.dumps({"run_id": run_id, "status": "RUNNING", "started_at": 1.0}), encoding="utf-8")
    (workspace_manager.workspace_root / run_id).mkdir(parents=True)
    (artifact_store.root / task.task_id).mkdir(parents=True)

    data = await cancel_demo_run(run_id)

    assert data["status"] == "DELETED"
    assert data["runtime_tasks_cancelled"] == 1
    assert store.list_tasks_for_run(run_id) == []
    assert task.task_id not in daemon_main.tasks
    assert not (workspace_manager.workspace_root / run_id).exists()
    assert not (artifact_store.root / task.task_id).exists()
    store.close()


@pytest.mark.anyio
async def test_demo_runtime_tasks_returns_empty_without_runtime_tasks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert await get_demo_runtime_tasks("run_without_tasks") == {"tasks": []}


@pytest.mark.anyio
async def test_run_task_once_restarts_worker_when_connect_times_out(monkeypatch, tmp_path):
    import aruntime.daemon.main as daemon_main

    task = TaskSpec(agent_name="architect", task_input={}, workspace=None)
    agent = AgentSpec(agent_name="architect", role="规划者", backend=AgentBackendConfig(type=AgentBackendType.DIRECT_TOOL))
    calls = {"wait": 0, "restart": 0}

    async def fake_wait_connected(agent_name, timeout_s=5.0):
        calls["wait"] += 1
        return calls["wait"] > 1

    async def fake_send_event(agent_name, event):
        result = daemon_main.pending_task_results[task.task_id]["future"]
        result.set_result({"status": "SUCCESS", "output": "ok", "token_usage": {}})
        return True

    monkeypatch.setattr(daemon_main.message_router, "wait_connected", fake_wait_connected)
    monkeypatch.setattr(daemon_main.message_router, "send_event", fake_send_event)
    monkeypatch.setattr(daemon_main, "_ensure_worker_started", lambda agent_name: calls.__setitem__("restart", calls["restart"] + 1))
    monkeypatch.setattr(daemon_main, "_record_trace_event", lambda *args, **kwargs: None)

    output = await daemon_main._run_task_once(task, agent, {}, "{}", None)

    assert output == "ok"
    assert calls == {"wait": 2, "restart": 1}
