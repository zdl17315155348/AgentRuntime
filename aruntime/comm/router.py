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
        self._unacked: dict[str, Message] = {}
        self._processed: dict[str, set[str]] = defaultdict(set)
        self._retry_count: dict[str, int] = defaultdict(int)
        self._connections: dict[str, asyncio.StreamWriter] = {}
        self._conn_locks: dict[str, asyncio.Lock] = {}
        self._connected_events: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._mailbox_max = int(os.getenv("AGENTD_MAILBOX_MAX", "1000"))
        self._store = store

    def _enqueue_locked(self, message: Message) -> None:
        if message.message_id in self._processed[message.to_agent]:
            return
        mailbox = self._mailboxes[message.to_agent]
        if self._mailbox_max > 0 and len(mailbox) >= self._mailbox_max:
            dropped = mailbox.popleft()
            self._dead_letters[dropped.to_agent].append(dropped)
            if self._store is not None:
                self._store.save_mailbox_message(dropped, dead_letter=True)
        mailbox.append(message)
        if self._store is not None:
            self._store.save_mailbox_message(message, dead_letter=False)
        if message.ack_required:
            self._unacked[message.message_id] = message

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
                message = mailbox.popleft()
                if message.message_id in self._processed[agent_name]:
                    continue
                messages.append(message)
            if self._store is not None:
                self._store.delete_mailbox_messages([message.message_id for message in messages])
            return messages

    async def ack(self, agent_name: str, message_id: str) -> bool:
        async with self._lock:
            message = self._unacked.pop(message_id, None)
            self._processed[agent_name].add(message_id)
            if self._store is not None:
                self._store.delete_mailbox_messages([message_id])
            return message is not None

    async def replay_unacked(self, agent_name: str, max_retries: int = 3) -> int:
        async with self._lock:
            messages = [msg for msg in self._unacked.values() if msg.to_agent == agent_name]
            replay: list[Message] = []
            for msg in messages:
                self._retry_count[msg.message_id] += 1
                if self._retry_count[msg.message_id] > max_retries:
                    self._dead_letters[msg.to_agent].append(msg)
                    self._unacked.pop(msg.message_id, None)
                    if self._store is not None:
                        self._store.save_mailbox_message(msg, dead_letter=True)
                else:
                    replay.append(msg)
        for msg in replay:
            async with self._lock:
                self._mailboxes[agent_name].appendleft(msg)
                if self._store is not None:
                    self._store.save_mailbox_message(msg, dead_letter=False)
        return len(replay)

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
            connection_lock = asyncio.Lock()
            self._connections[agent_name] = writer
            self._conn_locks[agent_name] = connection_lock
            ev = self._connected_events.get(agent_name)
            if ev is None:
                ev = asyncio.Event()
                self._connected_events[agent_name] = ev
            queued = list(self._mailboxes.get(agent_name, deque()))
            queued_ids = {msg.message_id for msg in queued}
            queued.extend(
                msg
                for msg in self._unacked.values()
                if msg.to_agent == agent_name and msg.message_id not in queued_ids
            )
            self._mailboxes[agent_name] = deque()
            ev.set()
        if self._store is not None and queued:
            self._store.delete_mailbox_messages([msg.message_id for msg in queued])

        for msg in queued:
            ok = await self._send_to_writer(agent_name, msg, writer, connection_lock)
            if not ok:
                await self._requeue_after_send_failure(agent_name, msg, writer)

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
            connection_lock = self._conn_locks.get(message.to_agent)
            if writer is None or connection_lock is None:
                self._enqueue_locked(message)
                return
        ok = await self._send_to_writer(message.to_agent, message, writer, connection_lock)
        if not ok:
            await self._requeue_after_send_failure(message.to_agent, message, writer)

    async def wait_connected(self, agent_name: str, timeout_s: float = 5.0) -> bool:
        async with self._lock:
            if agent_name in self._connections:
                return True
            ev = self._connected_events.get(agent_name)
            if ev is None:
                ev = asyncio.Event()
                self._connected_events[agent_name] = ev
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return False
        async with self._lock:
            return agent_name in self._connections

    async def send_event(self, agent_name: str, event: dict) -> bool:
        async with self._lock:
            writer = self._connections.get(agent_name)
            connection_lock = self._conn_locks.get(agent_name)
        if writer is None or connection_lock is None:
            return False

        line = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            async with connection_lock:
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
        writer: asyncio.StreamWriter,
        connection_lock: asyncio.Lock,
    ) -> bool:
        data = {"type": "message", **message.model_dump(mode="json")}
        line = (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            async with connection_lock:
                writer.write(line)
                await writer.drain()
            return True
        except Exception:
            await self.unregister(agent_name, writer)
            return False

    async def _requeue_after_send_failure(
        self,
        agent_name: str,
        message: Message,
        failed_writer: asyncio.StreamWriter,
    ) -> None:
        retry_writer = None
        retry_lock = None

        async with self._lock:
            current_writer = self._connections.get(agent_name)
            current_lock = self._conn_locks.get(agent_name)

            if (
                current_writer is not None
                and current_lock is not None
                and current_writer is not failed_writer
            ):
                retry_writer = current_writer
                retry_lock = current_lock
            else:
                self._enqueue_locked(message)

        if retry_writer is not None and retry_lock is not None:
            ok = await self._send_to_writer(
                agent_name,
                message,
                retry_writer,
                retry_lock,
            )
            if not ok:
                async with self._lock:
                    self._enqueue_locked(message)
