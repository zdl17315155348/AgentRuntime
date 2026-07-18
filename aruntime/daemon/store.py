import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from aruntime.comm.message import Message
from aruntime.core.models import AgentSpec, TaskSpec
from aruntime.resource.types import ResourceLease


class SQLiteStateStore:
    def __init__(self, path: str | None = None):
        default_path = os.path.join("/tmp", "agent-runtime-os", "state.db")
        self.path = path or os.getenv("AGENTD_STATE_DB", default_path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute(
            "CREATE TABLE IF NOT EXISTS agents ("
            "agent_name TEXT PRIMARY KEY, status TEXT, worker_pid INTEGER, "
            "auth_token TEXT, last_heartbeat TEXT, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS tasks ("
            "task_id TEXT PRIMARY KEY, agent_name TEXT, state TEXT, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS task_attempts ("
            "attempt_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, agent_name TEXT, "
            "worker_pid INTEGER, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS resource_leases ("
            "lease_id TEXT PRIMARY KEY, task_id TEXT, agent_name TEXT, status TEXT, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS mailbox_messages ("
            "message_id TEXT PRIMARY KEY, mailbox TEXT NOT NULL, dead_letter INTEGER DEFAULT 0, "
            "data TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS trace_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT, task_id TEXT, name TEXT, "
            "data TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS processed_messages ("
            "message_id TEXT NOT NULL, receiver TEXT NOT NULL, status TEXT NOT NULL, "
            "processed_at TEXT, generated_task_id TEXT, PRIMARY KEY(message_id, receiver))"
        )
        self._conn.commit()

    def save_agent(
        self,
        agent: AgentSpec,
        worker_pid: int | None = None,
        auth_token: str = "",
        last_heartbeat: datetime | None = None,
    ) -> None:
        data = agent.model_dump(mode="json")
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO agents "
                "(agent_name, status, worker_pid, auth_token, last_heartbeat, data, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    agent.agent_name,
                    agent.status.value,
                    worker_pid,
                    auth_token,
                    last_heartbeat.isoformat() if last_heartbeat else None,
                    json.dumps(data, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            self._conn.commit()

    def load_agents(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM agents").fetchall()
            return [dict(row) for row in rows]

    def save_task(self, task: TaskSpec) -> None:
        data = task.model_dump(mode="json")
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO tasks (task_id, agent_name, state, data, updated_at) VALUES (?, ?, ?, ?, ?)",
                (
                    task.task_id,
                    task.agent_name,
                    task.status.value,
                    json.dumps(data, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            for attempt in task.attempts:
                self._conn.execute(
                    "INSERT OR REPLACE INTO task_attempts "
                    "(attempt_id, task_id, agent_name, worker_pid, data, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        attempt.attempt_id,
                        task.task_id,
                        attempt.agent_name,
                        attempt.worker_pid,
                        json.dumps(attempt.model_dump(mode="json"), ensure_ascii=False),
                        datetime.now().isoformat(),
                    ),
                )
            self._conn.commit()

    def load_tasks(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM tasks").fetchall()
            return [dict(row) for row in rows]

    def save_lease(self, lease: ResourceLease) -> None:
        data = lease.to_dict()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO resource_leases "
                "(lease_id, task_id, agent_name, status, data, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    lease.lease_id,
                    lease.task_id,
                    lease.agent_name,
                    lease.status,
                    json.dumps(data, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            self._conn.commit()

    def release_leases_for_task(self, task_id: str, reason: str = "") -> None:
        with self._lock:
            rows = self._conn.execute(
                "SELECT lease_id, data FROM resource_leases WHERE task_id = ? AND status = 'active'",
                (task_id,),
            ).fetchall()
            for row in rows:
                data = json.loads(row["data"])
                data["status"] = "released"
                data["released_at"] = datetime.now().isoformat()
                data["reason"] = reason
                self._conn.execute(
                    "UPDATE resource_leases SET status = 'released', data = ?, updated_at = ? WHERE lease_id = ?",
                    (json.dumps(data, ensure_ascii=False), datetime.now().isoformat(), row["lease_id"]),
                )
            self._conn.commit()

    def release_all_active_leases(self, reason: str = "daemon.recovery") -> None:
        with self._lock:
            rows = self._conn.execute("SELECT task_id FROM resource_leases WHERE status = 'active'").fetchall()
            task_ids = [row["task_id"] for row in rows]
            for task_id in task_ids:
                self._release_leases_for_task_unlocked(task_id, reason=reason)
            self._conn.commit()

    def _release_leases_for_task_unlocked(self, task_id: str, reason: str = "") -> None:
        rows = self._conn.execute(
            "SELECT lease_id, data FROM resource_leases WHERE task_id = ? AND status = 'active'",
            (task_id,),
        ).fetchall()
        for row in rows:
            data = json.loads(row["data"])
            data["status"] = "released"
            data["released_at"] = datetime.now().isoformat()
            data["reason"] = reason
            self._conn.execute(
                "UPDATE resource_leases SET status = 'released', data = ?, updated_at = ? WHERE lease_id = ?",
                (json.dumps(data, ensure_ascii=False), datetime.now().isoformat(), row["lease_id"]),
            )

    def save_mailbox_message(self, message: Message, dead_letter: bool = False) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO mailbox_messages (message_id, mailbox, dead_letter, data, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    message.message_id,
                    message.to_agent,
                    1 if dead_letter else 0,
                    json.dumps(message.model_dump(mode="json"), ensure_ascii=False),
                    message.created_at.isoformat(),
                ),
            )
            self._conn.commit()

    def delete_mailbox_messages(self, message_ids: list[str]) -> None:
        if not message_ids:
            return
        with self._lock:
            self._conn.executemany("DELETE FROM mailbox_messages WHERE message_id = ?", [(mid,) for mid in message_ids])
            self._conn.commit()

    def load_mailbox_messages(self, dead_letter: bool = False) -> list[Message]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM mailbox_messages WHERE dead_letter = ? ORDER BY created_at ASC",
                (1 if dead_letter else 0,),
            ).fetchall()
            return [Message(**json.loads(row["data"])) for row in rows]

    def save_trace_event(self, trace_id: str, task_id: str, name: str, detail: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO trace_events (trace_id, task_id, name, data, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    trace_id,
                    task_id,
                    name,
                    json.dumps(detail or {}, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            self._conn.commit()

    def save_processed_message(
        self,
        message_id: str,
        receiver: str,
        status: str = "processed",
        generated_task_id: str = "",
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO processed_messages "
                "(message_id, receiver, status, processed_at, generated_task_id) VALUES (?, ?, ?, ?, ?)",
                (message_id, receiver, status, datetime.now().isoformat(), generated_task_id),
            )
            self._conn.commit()

    def processed_message_exists(self, message_id: str, receiver: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM processed_messages WHERE message_id = ? AND receiver = ?",
                (message_id, receiver),
            ).fetchone()
            return row is not None

    def counts(self) -> dict[str, int]:
        result = {}
        with self._lock:
            for table in ("agents", "tasks", "task_attempts", "resource_leases", "mailbox_messages", "trace_events", "processed_messages"):
                result[table] = int(self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            result["dead_letter_messages"] = int(
                self._conn.execute("SELECT COUNT(*) FROM mailbox_messages WHERE dead_letter = 1").fetchone()[0]
            )
        return result
