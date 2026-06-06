import asyncio
import json
import os

from aruntime.comm.message import Message
from aruntime.comm.router import MessageRouter


def _encode_line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def _decode_line(line: bytes) -> dict:
    return json.loads(line.decode("utf-8").strip())


async def _handle_uds_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    router: MessageRouter,
    task_result_handler,
) -> None:
    agent_name = ""
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        if not line:
            return
        first = _decode_line(line)
        if first.get("type") != "register":
            return
        agent_name = str(first.get("agent_name") or "").strip()
        if not agent_name:
            return

        await router.register(agent_name, writer)

        while True:
            line = await reader.readline()
            if not line:
                break
            data = _decode_line(line)
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
            if msg_type == "task_result" and task_result_handler is not None:
                await task_result_handler(agent_name, data)
                task_id = data.get("task_id")
                if task_id:
                    writer.write(_encode_line({"type": "ack", "task_id": task_id}))
                    await writer.drain()
    finally:
        if agent_name:
            await router.unregister(agent_name)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def start_uds_server(path: str, router: MessageRouter, task_result_handler=None) -> asyncio.AbstractServer:
    if os.path.exists(path):
        os.remove(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return await asyncio.start_unix_server(
        lambda r, w: _handle_uds_client(r, w, router, task_result_handler),
        path=path,
    )


class UDSMessageClient:
    def __init__(self, path: str, agent_name: str):
        self.path = path
        self.agent_name = agent_name
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        reader, writer = await asyncio.open_unix_connection(self.path)
        writer.write(_encode_line({"type": "register", "agent_name": self.agent_name}))
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
            await self._writer.wait_closed()
        finally:
            self._writer = None
            self._reader = None
