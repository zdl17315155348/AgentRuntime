from collections import defaultdict, deque
from threading import Lock
from typing import Deque

from aruntime.comm.message import Message


class MessageRouter:
    def __init__(self):
        self._mailboxes: dict[str, Deque[Message]] = defaultdict(deque)
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

