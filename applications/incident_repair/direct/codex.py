from __future__ import annotations

import asyncio
import json
import os
import shutil
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
        codex_home: str | None = None,
    ) -> tuple[int | None, str, str, int | None]:
        prompt = build_codex_prompt(system_prompt, goal, task_input or {}, runtime_context or {}, cwd)
        command = [
            self.executable,
            "--ask-for-approval",
            "never",
            "exec",
            "--sandbox",
            "read-only" if role == "reviewer" else "workspace-write",
            "--ephemeral",
            "--json",
            "--skip-git-repo-check",
        ]
        if output_schema:
            command.extend(["--output-schema", str(Path(output_schema).resolve())])
        if output_last_message:
            command.extend(["--output-last-message", output_last_message])
        command.append(prompt)
        attempts = max(1, int(os.getenv("CODEX_EXEC_RETRIES", "2")))
        last: tuple[int | None, str, str, int | None] = (1, "", "", None)
        for attempt in range(attempts):
            if output_last_message:
                try:
                    Path(output_last_message).unlink()
                except FileNotFoundError:
                    pass
            last = await self._run_command(command, cwd, timeout_s, codex_home=codex_home)
            rc, stdout, stderr, pid = last
            if rc == 0 or not _is_retryable_codex_failure(stdout, stderr):
                return last
            if attempt + 1 < attempts:
                await asyncio.sleep(2 * (attempt + 1))
        return last

    async def _run_command(self, command: list[str], cwd: str, timeout_s: int, codex_home: str | None = None) -> tuple[int | None, str, str, int | None]:
        env = os.environ.copy()
        api_key = os.getenv("CODEX_API_KEY") or os.getenv("OPENAI_API_KEY")
        if api_key:
            env["CODEX_API_KEY"] = api_key
        env["CODEX_HOME"] = str(
            _prepare_codex_home(
                codex_home or cwd,
                require_config=Path(self.executable).name == "codex",
                as_home=codex_home is not None,
            )
        )
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
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=3)
            except TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, stderr = await process.communicate()
            return None, stdout.decode("utf-8", errors="replace"), f"codex timeout\n{stderr.decode('utf-8', errors='replace')}", process.pid


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


def _prepare_codex_home(cwd: str, require_config: bool = True, as_home: bool = False) -> Path:
    target = Path(cwd) if as_home else Path(cwd) / ".codex-home"
    target.mkdir(parents=True, exist_ok=True)
    source_home = Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex")))
    source_config = source_home / "config.toml"
    target_config = target / "config.toml"
    if require_config and not source_config.exists():
        raise FileNotFoundError(f"missing Codex config: {source_config}")
    if source_config.exists() and not target_config.exists():
        shutil.copyfile(source_config, target_config)
    return target


def _is_retryable_codex_failure(stdout: str, stderr: str) -> bool:
    text = f"{stdout}\n{stderr}"
    return "stream disconnected before completion" in text or "Upstream request failed" in text


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
