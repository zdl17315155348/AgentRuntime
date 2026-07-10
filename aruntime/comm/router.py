import asyncio
import json
import os
from collections import defaultdict, deque
from typing import Deque

from aruntime.comm.message import Message


class MessageRouter:
    def __init__(self, store=None):
        self._mailboxes: dict[str, Deque[Message]] = defaultdict(deque)
        self._dead_letters: dict[str, Deque[Message]] = defaultdict(deque)
        self._connections: dict[str, asyncio.StreamWriter] = {}
        self._conn_locks: dict[str, asyncio.Lock] = {}
        self._connected_events: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._mailbox_max = int(os.getenv("AGENTD_MAILBOX_MAX", "1000"))
        self._store = store

    def _enqueue_locked(self, message: Message) -> None:
        mailbox = self._mailboxes[message.to_agent]
        if self._mailbox_max > 0 and len(mailbox) >= self._mailbox_max:
            dropped = mailbox.popleft()
            self._dead_letters[dropped.to_agent].append(dropped)
            if self._store is not None:
                self._store.save_mailbox_message(dropped, dead_letter=True)
        mailbox.append(message)
        if self._store is not None:
            self._store.save_mailbox_message(message, dead_letter=False)

    def restore_mailbox(self, messages: list[Message]) -> None:
        for message in messages:
            self._mailboxes[message.to_agent].append(message)

    async def send(self, message: Message) -> None:
        async with self._lock:
            self._enqueue_locked(message)

    async def receive(self, agent_name: str, limit: int = 50) -> list[Message]:
        if limit <= 0:
            return []
        async with self._lock:
            mailbox = self._mailboxes.get(agent_name)
            if not mailbox:
                return []
            messages: list[Message] = []
            for _ in range(min(limit, len(mailbox))):
                messages.append(mailbox.popleft())
            if self._store is not None:
                self._store.delete_mailbox_messages([message.message_id for message in messages])
            return messages

    async def dead_letters(self, agent_name: str | None = None, limit: int = 50) -> list[Message]:
        async with self._lock:
            if agent_name:
                items = list(self._dead_letters.get(agent_name, deque()))[:limit]
                return items
            result: list[Message] = []
            for mailbox in self._dead_letters.values():
                result.extend(list(mailbox))
            return result[:limit]

    async def register(self, agent_name: str, writer: asyncio.StreamWriter) -> None:
        async with self._lock:
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
            if self._store is not None:
                self._store.delete_mailbox_messages([msg.message_id for msg in queued])

        for msg in queued:
            await self._send_to_writer(agent_name, msg)

    async def unregister(self, agent_name: str, writer: asyncio.StreamWriter | None = None) -> None:
        async with self._lock:
            if writer is not None and self._connections.get(agent_name) is not writer:
                return
            self._connections.pop(agent_name, None)
            self._conn_locks.pop(agent_name, None)
            ev = self._connected_events.get(agent_name)
            if ev is not None:
                ev.clear()

    async def route(self, message: Message) -> None:
        async with self._lock:
            writer = self._connections.get(message.to_agent)
            w_lock = self._conn_locks.get(message.to_agent)
            if writer is None or w_lock is None:
                self._enqueue_locked(message)
                return
        await self._send_to_writer(message.to_agent, message, writer, w_lock)

    async def wait_connected(self, agent_name: str, timeout_s: float = 5.0) -> bool:
        async with self._lock:
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
        async with self._lock:
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
            await self.unregister(agent_name, writer)
            return False

    async def _send_to_writer(
        self,
        agent_name: str,
        message: Message,
        writer: asyncio.StreamWriter | None = None,
        w_lock: asyncio.Lock | None = None,
    ) -> None:
        if writer is None or w_lock is None:
            async with self._lock:
                writer = self._connections.get(agent_name)
                w_lock = self._conn_locks.get(agent_name)
        if writer is None or w_lock is None:
            await self.send(message)
            return

        data = {"type": "message", **message.model_dump(mode="json")}
        line = (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            async with w_lock:
                writer.write(line)
                await writer.drain()
        except Exception:
            await self.unregister(agent_name, writer)
            async with self._lock:
                current_writer = self._connections.get(agent_name)
                current_lock = self._conn_locks.get(agent_name)
                if current_writer is None or current_lock is None:
                    self._enqueue_locked(message)
                    return
            await self._send_to_writer(agent_name, message, current_writer, current_lock)
