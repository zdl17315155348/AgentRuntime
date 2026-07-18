import asyncio

import pytest


@pytest.mark.anyio
async def test_running_table_is_attempt_scoped_and_cancel_targets_attempt():
    running: dict[tuple[str, str], asyncio.Task] = {}
    sent: list[dict] = []

    async def send_json(payload: dict) -> None:
        sent.append(payload)

    async def worker_task() -> None:
        await asyncio.sleep(10)

    async def start(task_id: str, attempt_id: str) -> None:
        key = (task_id, attempt_id)
        if key in running:
            await send_json(
                {
                    "type": "protocol_error",
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "error": "attempt already running",
                }
            )
            return
        task = asyncio.create_task(worker_task())
        running[key] = task

        def cleanup(done_task: asyncio.Task, task_key=key) -> None:
            if running.get(task_key) is done_task:
                running.pop(task_key, None)

        task.add_done_callback(cleanup)

    async def cancel(task_id: str, attempt_id: str) -> None:
        key = (task_id, attempt_id)
        task = running.get(key)
        if task is None:
            await send_json(
                {
                    "type": "cancel_ack",
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "cancelled": False,
                    "reason": "attempt_not_running",
                }
            )
            return
        task.cancel()
        await send_json({"type": "cancel_ack", "task_id": task_id, "attempt_id": attempt_id, "cancelled": True})

    await start("task-1", "attempt-1")
    await start("task-1", "attempt-2")
    await start("task-1", "attempt-1")
    assert sent[-1]["type"] == "protocol_error"
    assert sent[-1]["error"] == "attempt already running"

    await cancel("task-1", "missing")
    assert sent[-1]["cancelled"] is False
    assert sent[-1]["reason"] == "attempt_not_running"
    assert ("task-1", "attempt-1") in running
    assert ("task-1", "attempt-2") in running

    await cancel("task-1", "attempt-1")
    assert sent[-1]["cancelled"] is True
    for _ in range(10):
        if ("task-1", "attempt-1") not in running:
            break
        await asyncio.sleep(0)
    assert ("task-1", "attempt-1") not in running
    assert ("task-1", "attempt-2") in running

    running[("task-1", "attempt-2")].cancel()
