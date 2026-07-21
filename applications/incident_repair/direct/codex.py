from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Any


class DirectCodexExecutor:
    def __init__(self, executable: str = "codex"):
        self.executable = executable

    async def execute(
        self,
        goal: str,
        cwd: str,
        role: str,
        timeout_s: int,
        system_prompt: str = "",
        task_input: dict[str, Any] | None = None,
        runtime_context: dict[str, Any] | None = None,
        output_schema: str | None = None,
        output_last_message: str | None = None,
    ) -> tuple[int | None, str, str, int | None]:
        prompt = build_codex_prompt(system_prompt, goal, task_input or {}, runtime_context or {}, cwd)
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
        ]
        if output_schema:
            command.extend(["--output-schema", str(Path(output_schema).resolve())])
        if output_last_message:
            command.extend(["--output-last-message", output_last_message])
        command.append(prompt)
        env = os.environ.copy()
        api_key = os.getenv("CODEX_API_KEY") or os.getenv("OPENAI_API_KEY")
        if api_key:
            env["CODEX_API_KEY"] = api_key
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
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


def build_codex_prompt(system_prompt: str, goal: str, task_input: dict[str, Any], runtime_context: dict[str, Any], cwd: str) -> str:
    parts = []
    if system_prompt:
        parts.append(system_prompt)
    parts.append(f"Goal:\n{goal}")
    parts.append(f"Workspace:\n{cwd}")
    if task_input:
        parts.append("Task input JSON:\n" + json.dumps(task_input, ensure_ascii=False))
    if runtime_context:
        parts.append("Runtime context JSON:\n" + json.dumps(runtime_context, ensure_ascii=False))
    return "\n\n".join(parts)


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
