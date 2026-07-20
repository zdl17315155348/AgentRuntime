from __future__ import annotations

import asyncio

import pytest

from aruntime.daemon.main import CreateDemoRunRequest, create_demo_run, get_demo_events, get_demo_replay, get_demo_run


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
