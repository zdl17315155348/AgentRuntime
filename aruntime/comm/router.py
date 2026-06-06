import asyncio
import json
from collections import defaultdict, deque
from threading import Lock
from typing import Deque

from aruntime.comm.message import Message


class MessageRouter:
    def __init__(self):
        self._mailboxes: dict[str, Deque[Message]] = defaultdict(deque)
        self._connections: dict[str, asyncio.StreamWriter] = {}
        self._conn_locks: dict[str, asyncio.Lock] = {}
        self._connected_events: dict[str, asyncio.Event] = {}
        self._lock = Lock()

    def send(self, message: Message) -> None:
        with self._lock:
            self._mailboxes[message.to_agent].append(message)

    def receive(self, agent_name: str, limit: int = 50) -> list[Message]:
        if limit <= 0:
            return []
        with self._lock:
            mailbox = self._mailboxes.get(agent_name)
            if not mailbox:
                return []
            messages: list[Message] = []
            for _ in range(min(limit, len(mailbox))):
                messages.append(mailbox.popleft())
            return messages

    async def register(self, agent_name: str, writer: asyncio.StreamWriter) -> None:
        with self._lock:
            self._connections[agent_name] = writer
            self._conn_locks[agent_name] = asyncio.Lock()
            ev = self._connected_events.get(agent_name)
            if ev is None:
                ev = asyncio.Event()
                self._connected_events[agent_name] = ev
            ev.set()
            queued = list(self._mailboxes.get(agent_name, deque()))
            if queued:
                self._mailboxes[agent_name] = deque()

        for msg in queued:
            await self._send_to_writer(agent_name, msg)

    async def unregister(self, agent_name: str) -> None:
        with self._lock:
            self._connections.pop(agent_name, None)
            self._conn_locks.pop(agent_name, None)
            ev = self._connected_events.get(agent_name)
            if ev is not None:
                ev.clear()

    async def route(self, message: Message) -> None:
        with self._lock:
            online = message.to_agent in self._connections
        if not online:
            self.send(message)
            return
        await self._send_to_writer(message.to_agent, message)

    async def wait_connected(self, agent_name: str, timeout_s: float = 5.0) -> bool:
        with self._lock:
            ev = self._connected_events.get(agent_name)
            if ev is None:
                ev = asyncio.Event()
                self._connected_events[agent_name] = ev
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout_s)
            return True
        except Exception:
            return False

    async def send_event(self, agent_name: str, event: dict) -> bool:
        with self._lock:
            writer = self._connections.get(agent_name)
            w_lock = self._conn_locks.get(agent_name)
        if writer is None or w_lock is None:
            return False

        line = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            async with w_lock:
                writer.write(line)
                await writer.drain()
            return True
        except Exception:
            await self.unregister(agent_name)
            return False

    async def _send_to_writer(self, agent_name: str, message: Message) -> None:
        with self._lock:
            writer = self._connections.get(agent_name)
            w_lock = self._conn_locks.get(agent_name)
        if writer is None or w_lock is None:
            self.send(message)
            return

        data = {"type": "message", **message.model_dump(mode="json")}
        line = (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            async with w_lock:
                writer.write(line)
                await writer.drain()
        except Exception:
            await self.unregister(agent_name)
            self.send(message)
