import pytest

from aruntime.comm.message import Message
from aruntime.comm.router import MessageRouter
from aruntime.daemon.store import SQLiteStateStore


@pytest.mark.anyio
async def test_agent_message_ack_is_persisted_and_deduped(tmp_path):
    store = SQLiteStateStore(str(tmp_path / "state.db"))
    router = MessageRouter(store=store)
    msg = Message(from_agent="reviewer", to_agent="tester", payload={"action": "add_test"})

    await router.send(msg)
    delivered = await router.receive("tester", limit=10)
    assert [item.message_id for item in delivered] == [msg.message_id]

    store.save_processed_message(msg.message_id, "tester", status="processed", generated_task_id="task_extra")
    assert store.processed_message_exists(msg.message_id, "tester") is True
    assert await router.ack("tester", msg.message_id) is True

    await router.send(msg)
    again = await router.receive("tester", limit=10)
    assert again == []
