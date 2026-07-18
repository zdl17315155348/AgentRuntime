import asyncio

import pytest

from aruntime.comm.message import Message
from aruntime.comm.router import MessageRouter


class FakeWriter:
    def __init__(self):
        self.data = bytearray()
        self.drain_calls = 0

    def write(self, data: bytes) -> None:
        self.data.extend(data)

    async def drain(self) -> None:
        self.drain_calls += 1


class BlockingWriter:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    def write(self, data: bytes) -> None:
        self.started.set()

    async def drain(self) -> None:
        await self.release.wait()


class FailingWriter:
    def __init__(self):
        self.fail = False
        self.data = bytearray()

    def write(self, data: bytes) -> None:
        self.data.extend(data)
        if self.fail:
            raise RuntimeError("writer failed")

    async def drain(self) -> None:
        return None


def make_message(to_agent: str) -> Message:
    return Message(from_agent="sender", to_agent=to_agent, payload={"kind": "demo"})


@pytest.mark.anyio
async def test_register_replays_offline_message():
    router = MessageRouter()
    writer = FakeWriter()

    message = make_message("tester")
    await router.send(message)

    await asyncio.wait_for(router.register("tester", writer), timeout=1.0)

    assert writer.drain_calls == 1
    assert message.message_id.encode() in writer.data


@pytest.mark.anyio
async def test_wait_connected_unblocks_after_register():
    router = MessageRouter()
    writer = FakeWriter()

    waiter = asyncio.create_task(router.wait_connected("tester", timeout_s=1.0))

    await asyncio.sleep(0.05)
    await router.register("tester", writer)

    assert await waiter is True


@pytest.mark.anyio
async def test_slow_writer_does_not_block_other_agent():
    router = MessageRouter()
    slow_writer = BlockingWriter()
    fast_writer = FakeWriter()

    await router.register("slow", slow_writer)

    send_task = asyncio.create_task(router.send_event("slow", {"type": "slow"}))

    await slow_writer.started.wait()

    await asyncio.wait_for(router.register("fast", fast_writer), timeout=0.2)

    slow_writer.release.set()
    await send_task


@pytest.mark.anyio
async def test_route_failure_requeues_message():
    router = MessageRouter()
    writer = FailingWriter()

    await router.register("tester", writer)
    writer.fail = True

    message = make_message("tester")
    await asyncio.wait_for(router.route(message), timeout=1.0)

    received = await router.receive("tester")
    assert [item.message_id for item in received] == [message.message_id]


@pytest.mark.anyio
async def test_old_connection_failure_does_not_remove_new_connection():
    router = MessageRouter()
    old_writer = FailingWriter()
    new_writer = FakeWriter()

    await router.register("tester", old_writer)
    old_writer.fail = True
    await router.register("tester", new_writer)

    message = make_message("tester")
    await router.route(message)

    assert router._connections["tester"] is new_writer
