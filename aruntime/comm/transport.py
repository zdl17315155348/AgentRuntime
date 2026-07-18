import asyncio
import json
import os
import socket
import struct

from aruntime.comm.message import Message
from aruntime.comm.router import MessageRouter

MAX_MESSAGE_BYTES = int(os.getenv("AGENTD_UDS_MAX_MESSAGE_BYTES", "1048576"))


def _encode_line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def _decode_line(line: bytes) -> dict:
    if len(line) > MAX_MESSAGE_BYTES:
        raise ValueError("message too large")
    data = json.loads(line.decode("utf-8").strip())
    if not isinstance(data, dict):
        raise ValueError("message must be object")
    return data


async def _read_limited_line(reader: asyncio.StreamReader, timeout: float | None = None) -> bytes:
    coro = reader.readline()
    try:
        line = await asyncio.wait_for(coro, timeout=timeout) if timeout else await coro
    except ValueError as exc:
        raise ValueError("message too large") from exc
    if len(line) > MAX_MESSAGE_BYTES:
        raise ValueError("message too large")
    return line


def _peer_credentials(writer: asyncio.StreamWriter) -> dict:
    sock = writer.get_extra_info("socket")
    if sock is None or not hasattr(socket, "SO_PEERCRED"):
        return {}
    try:
        data = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, gid = struct.unpack("3i", data)
        return {"pid": pid, "uid": uid, "gid": gid}
    except Exception:
        return {}


def _valid_register(data: dict) -> bool:
    return data.get("type") == "register" and bool(str(data.get("agent_name") or "").strip())


def _valid_task_result(data: dict) -> bool:
    return (
        data.get("type") == "task_result"
        and bool(str(data.get("task_id") or "").strip())
        and data.get("status") in {"SUCCESS", "FAILED"}
    )


async def _handle_uds_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    router: MessageRouter,
    task_result_handler,
    auth_tokens: dict[str, str] | None = None,
    heartbeat_handler=None,
    agent_message_ack_handler=None,
) -> None:
    agent_name = ""
    seen_message_ids: set[str] = set()
    try:
        try:
            line = await _read_limited_line(reader, timeout=5.0)
            if not line:
                return
            first = _decode_line(line)
        except Exception:
            return
        if not _valid_register(first):
            return
        agent_name = str(first.get("agent_name") or "").strip()
        if not agent_name:
            return
        expected = (auth_tokens or {}).get(agent_name)
        if expected and first.get("token") != expected:
            return
        peer = _peer_credentials(writer)
        allowed_uid = os.getenv("AGENTD_ALLOWED_UID", "")
        if allowed_uid and peer.get("uid") != int(allowed_uid):
            return

        await router.register(agent_name, writer)
        if heartbeat_handler is not None:
            await heartbeat_handler(agent_name, {"type": "register", "peer": peer})

        while True:
            try:
                line = await _read_limited_line(reader)
                if not line:
                    break
                data = _decode_line(line)
            except Exception:
                break
            msg_type = data.get("type")
            if msg_type == "send":
                to_agent = str(data.get("to_agent") or "").strip()
                if not to_agent:
                    continue
                payload = data.get("payload")
                if not isinstance(payload, dict):
                    continue
                topic = data.get("topic")
                msg = Message(
                    from_agent=agent_name,
                    to_agent=to_agent,
                    payload=payload,
                    topic=str(topic) if topic else None,
                )
                await router.route(msg)
                continue
            if msg_type == "heartbeat":
                if heartbeat_handler is not None:
                    await heartbeat_handler(agent_name, {"type": "heartbeat", "peer": peer})
                continue
            if msg_type == "task_result" and task_result_handler is not None:
                if not _valid_task_result(data):
                    continue
                message_id = str(data.get("message_id") or "")
                if message_id and message_id in seen_message_ids:
                    try:
                        writer.write(_encode_line({"type": "ack", "task_id": data.get("task_id"), "message_id": message_id}))
                        await writer.drain()
                    except Exception:
                        break
                    continue
                if message_id:
                    seen_message_ids.add(message_id)
                await task_result_handler(agent_name, data)
                task_id = data.get("task_id")
                if task_id:
                    try:
                        writer.write(_encode_line({"type": "ack", "task_id": task_id, "message_id": data.get("message_id", "")}))
                        await writer.drain()
                    except Exception:
                        break
                continue
            if msg_type == "agent_message_ack":
                message_id = str(data.get("message_id") or "")
                if message_id:
                    if agent_message_ack_handler is not None:
                        await agent_message_ack_handler(agent_name, data)
                    else:
                        await router.ack(agent_name, message_id)
                continue
    finally:
        if agent_name:
            await router.unregister(agent_name, writer)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def start_uds_server(
    path: str,
    router: MessageRouter,
    task_result_handler=None,
    auth_tokens: dict[str, str] | None = None,
    heartbeat_handler=None,
    agent_message_ack_handler=None,
) -> asyncio.AbstractServer:
    if os.path.exists(path):
        os.remove(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    server = await asyncio.start_unix_server(
        lambda r, w: _handle_uds_client(r, w, router, task_result_handler, auth_tokens, heartbeat_handler, agent_message_ack_handler),
        path=path,
    )
    os.chmod(path, 0o660)
    return server


class UDSMessageClient:
    def __init__(self, path: str, agent_name: str, token: str = ""):
        self.path = path
        self.agent_name = agent_name
        self.token = token
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        reader, writer = await asyncio.open_unix_connection(self.path)
        writer.write(_encode_line({"type": "register", "agent_name": self.agent_name, "token": self.token}))
        await writer.drain()
        self._reader = reader
        self._writer = writer

    async def send(self, to_agent: str, payload: dict, topic: str = "") -> None:
        if self._writer is None:
            raise RuntimeError("not connected")
        self._writer.write(_encode_line({"type": "send", "to_agent": to_agent, "payload": payload, "topic": topic}))
        await self._writer.drain()

    async def recv(self) -> dict | None:
        if self._reader is None:
            raise RuntimeError("not connected")
        line = await self._reader.readline()
        if not line:
            return None
        return _decode_line(line)

    async def close(self) -> None:
        if self._writer is None:
            return
        try:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        finally:
            self._writer = None
            self._reader = None
