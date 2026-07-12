import asyncio

import pytest

from aruntime.comm.message import Message
from aruntime.comm.router import MessageRouter


@pytest.mark.anyio
async def test_message_router_send_and_receive_consumes():
    r = MessageRouter()
    m1 = Message(from_agent="a", to_agent="b", payload={"k": 1})
    m2 = Message(from_agent="a", to_agent="b", payload={"k": 2})
    await r.send(m1)
    await r.send(m2)

    got = await r.receive("b", limit=10)
    assert [m.payload for m in got] == [{"k": 1}, {"k": 2}]

    got2 = await r.receive("b", limit=10)
    assert got2 == []


@pytest.mark.anyio
async def test_message_router_limit():
    r = MessageRouter()
    await r.send(Message(from_agent="a", to_agent="b", payload={"i": 1}))
    await r.send(Message(from_agent="a", to_agent="b", payload={"i": 2}))
    got = await r.receive("b", limit=1)
    assert len(got) == 1
    got2 = await r.receive("b", limit=10)
    assert len(got2) == 1


@pytest.mark.anyio
async def test_message_router_mailbox_max_moves_oldest_to_dead_letter(monkeypatch):
    monkeypatch.setenv("AGENTD_MAILBOX_MAX", "1")
    r = MessageRouter()
    await r.send(Message(from_agent="a", to_agent="b", payload={"i": 1}))
    await r.send(Message(from_agent="a", to_agent="b", payload={"i": 2}))
    got = await r.receive("b", limit=10)
    assert [m.payload for m in got] == [{"i": 2}]
    dead = await r.dead_letters("b", limit=10)
    assert [m.payload for m in dead] == [{"i": 1}]


class _BrokenWriter:
    def write(self, data: bytes) -> None:
        raise ConnectionError("closed")

    async def drain(self) -> None:
        return None


@pytest.mark.anyio
async def test_message_router_concurrent_offline_routes_do_not_deadlock():
    r = MessageRouter()

    async def route_one(i: int) -> None:
        await r.route(Message(from_agent="a", to_agent="offline", payload={"i": i}))

    await asyncio.wait_for(asyncio.gather(*(route_one(i) for i in range(20))), timeout=1.0)

    got = await asyncio.wait_for(r.receive("offline", limit=50), timeout=1.0)
    assert sorted(m.payload["i"] for m in got) == list(range(20))


@pytest.mark.anyio
async def test_message_router_disconnect_during_route_requeues_without_deadlock():
    r = MessageRouter()
    await r.register("b", _BrokenWriter())

    msg = Message(from_agent="a", to_agent="b", payload={"i": 1})
    await asyncio.wait_for(r.route(msg), timeout=1.0)

    got = await asyncio.wait_for(r.receive("b", limit=10), timeout=1.0)
    assert [m.payload for m in got] == [{"i": 1}]
    assert await asyncio.wait_for(r.wait_connected("b", timeout_s=0.01), timeout=1.0) is False


@pytest.mark.anyio
async def test_message_router_register_flush_requeues_without_deadlock():
    r = MessageRouter()
    await r.send(Message(from_agent="a", to_agent="b", payload={"i": 1}))

    await asyncio.wait_for(r.register("b", _BrokenWriter()), timeout=1.0)

    got = await asyncio.wait_for(r.receive("b", limit=10), timeout=1.0)
    assert [m.payload for m in got] == [{"i": 1}]
    assert await asyncio.wait_for(r.wait_connected("b", timeout_s=0.01), timeout=1.0) is False


@pytest.mark.anyio
async def test_message_router_reconnect_keeps_new_connection_event():
    r = MessageRouter()
    old_writer = _BrokenWriter()
    new_writer = _BrokenWriter()

    await r.register("b", old_writer)
    await r.register("b", new_writer)
    await asyncio.wait_for(r.unregister("b", old_writer), timeout=1.0)

    assert await asyncio.wait_for(r.wait_connected("b", timeout_s=0.01), timeout=1.0) is True
