import os

import anyio
import pytest

from aruntime.comm.router import MessageRouter
from aruntime.comm.transport import UDSMessageClient, start_uds_server


@pytest.mark.anyio
async def test_uds_offline_queue_flush(tmp_path):
    sock_path = tmp_path / "agentd.sock"
    router = MessageRouter()
    server = await start_uds_server(str(sock_path), router)
    a = None
    b = None
    try:
        a = UDSMessageClient(str(sock_path), "A")
        await a.connect()
        await a.send("B", {"x": 1})

        b = UDSMessageClient(str(sock_path), "B")
        await b.connect()

        with anyio.fail_after(2):
            msg = await b.recv()
        assert msg is not None
        assert msg["type"] == "message"
        assert msg["from_agent"] == "A"
        assert msg["to_agent"] == "B"
        assert msg["payload"] == {"x": 1}
    finally:
        if a is not None:
            await a.close()
        if b is not None:
            await b.close()
        server.close()
        await server.wait_closed()
        if os.path.exists(sock_path):
            os.remove(sock_path)


@pytest.mark.anyio
async def test_uds_online_push(tmp_path):
    sock_path = tmp_path / "agentd.sock"
    router = MessageRouter()
    server = await start_uds_server(str(sock_path), router)
    a = None
    b = None
    try:
        a = UDSMessageClient(str(sock_path), "A")
        b = UDSMessageClient(str(sock_path), "B")
        await a.connect()
        await b.connect()

        await a.send("B", {"hello": "world"}, topic="t")
        with anyio.fail_after(2):
            msg = await b.recv()
        assert msg is not None
        assert msg["type"] == "message"
        assert msg["from_agent"] == "A"
        assert msg["to_agent"] == "B"
        assert msg["payload"] == {"hello": "world"}
    finally:
        if a is not None:
            await a.close()
        if b is not None:
            await b.close()
        server.close()
        await server.wait_closed()
        if os.path.exists(sock_path):
            os.remove(sock_path)
