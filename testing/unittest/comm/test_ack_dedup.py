import pytest

from aruntime.comm.message import Message
from aruntime.comm.router import MessageRouter


@pytest.mark.anyio
async def test_ack_removes_unacked_message():
    router = MessageRouter()
    msg = Message(message_id="m1", from_agent="a", to_agent="b", payload={"x": 1})
    await router.send(msg)

    assert await router.ack("b", "m1") is True
    assert await router.replay_unacked("b") == 0


@pytest.mark.anyio
async def test_duplicate_message_is_not_delivered_after_ack():
    router = MessageRouter()
    msg = Message(message_id="m1", from_agent="a", to_agent="b", payload={"x": 1})
    await router.send(msg)
    await router.ack("b", "m1")
    await router.send(msg)

    assert await router.receive("b") == []


@pytest.mark.anyio
async def test_unacked_message_can_be_replayed():
    router = MessageRouter()
    msg = Message(message_id="m1", from_agent="a", to_agent="b", payload={"x": 1})
    await router.send(msg)
    await router.receive("b")

    assert await router.replay_unacked("b") == 1
    got = await router.receive("b")
    assert [item.message_id for item in got] == ["m1"]
