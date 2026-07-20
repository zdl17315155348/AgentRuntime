from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path


class DirectCodexExecutor:
    def __init__(self, executable: str = "codex"):
        self.executable = executable

    async def execute(self, goal: str, cwd: str, role: str, timeout_s: int) -> tuple[int | None, str, str, int | None]:
        command = [
            self.executable,
            "--sandbox",
            "read-only" if role == "reviewer" else "workspace-write",
            "--ask-for-approval",
            "never",
            "exec",
            "--ephemeral",
            "--json",
            "--skip-git-repo-check",
            goal,
        ]
        env = os.environ.copy()
        api_key = os.getenv("CODEX_API_KEY") or os.getenv("OPENAI_API_KEY")
        if api_key:
            env["CODEX_API_KEY"] = api_key
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
            return process.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace"), process.pid
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            return None, "", "codex timeout", process.pid


def last_agent_message(jsonl: str) -> str:
    message = ""
    for line in jsonl.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            message = str(item.get("text") or "")
    return message


def write_codex_events(path: str, jsonl: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(jsonl, encoding="utf-8")
