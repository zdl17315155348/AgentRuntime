import os
import stat
import time

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


@pytest.mark.anyio
async def test_uds_socket_has_0660_permissions(tmp_path):
    sock_path = tmp_path / "agentd.sock"
    router = MessageRouter()
    server = await start_uds_server(str(sock_path), router)
    try:
        mode = stat.S_IMODE(os.stat(sock_path).st_mode)
        assert mode == 0o660
    finally:
        server.close()
        await server.wait_closed()
        if os.path.exists(sock_path):
            os.remove(sock_path)


@pytest.mark.anyio
async def test_uds_rejects_oversized_message(tmp_path):
    sock_path = tmp_path / "agentd.sock"
    router = MessageRouter()
    server = await start_uds_server(str(sock_path), router)
    client = None
    try:
        client = UDSMessageClient(str(sock_path), "A")
        await client.connect()
        assert client._writer is not None
        client._writer.write(b"{" + b'"x":"' + b"a" * 2_000_000 + b'"}\n')
        with pytest.raises(Exception):
            await client._writer.drain()
    finally:
        if client is not None:
            await client.close()
        server.close()
        await server.wait_closed()
        if os.path.exists(sock_path):
            os.remove(sock_path)


@pytest.mark.anyio
async def test_uds_register_token_is_forwarded(tmp_path):
    sock_path = tmp_path / "agentd.sock"
    router = MessageRouter()
    seen = {}

    async def heartbeat(agent_name: str, data: dict) -> None:
        seen["agent_name"] = agent_name
        seen["data"] = data

    server = await start_uds_server(str(sock_path), router, auth_tokens={"A": "secret"}, heartbeat_handler=heartbeat)
    client = None
    try:
        client = UDSMessageClient(str(sock_path), "A", token="secret")
        await client.connect()
        deadline = time.time() + 1.0
        while "agent_name" not in seen and time.time() < deadline:
            await anyio.sleep(0.01)
        assert seen["agent_name"] == "A"
        assert seen["data"]["type"] == "register"
    finally:
        if client is not None:
            await client.close()
        server.close()
        await server.wait_closed()
        if os.path.exists(sock_path):
            os.remove(sock_path)
