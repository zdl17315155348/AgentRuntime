from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
from pathlib import Path
from typing import Any
from uuid import uuid4

from aruntime.backends.base import AgentBackend, BackendExecutionRequest, BackendExecutionResult, EmitEvent
from aruntime.core.models import AgentBackendConfig, AgentBackendType
from aruntime.workspace.artifact_store import ArtifactStore


class CodexCLIBackend(AgentBackend):
    def __init__(self, config: AgentBackendConfig, dependencies: dict):
        self.config = config
        self.artifact_store: ArtifactStore = dependencies.get("artifact_store") or ArtifactStore()
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    async def prepare(self, request: BackendExecutionRequest) -> None:
        if not request.workspace.workspace_path:
            raise ValueError("workspace_path is required for codex_cli backend")
        if self.config.sandbox == "danger-full-access":
            raise ValueError("danger-full-access is disabled by default")

    def build_command(self, request: BackendExecutionRequest) -> list[str]:
        prompt = self._build_prompt(request)
        command = [
            self.config.executable,
            "--ask-for-approval",
            self.config.approval_policy,
            "exec",
            "--sandbox",
            self.config.sandbox,
        ]
        if self.config.ephemeral:
            command.append("--ephemeral")
        command.append("--json")
        if self.config.output_schema:
            command.extend(["--output-schema", self._schema_path(self.config.output_schema)])
        final_path = self._final_json_path(request)
        command.extend(["--output-last-message", str(final_path), prompt])
        return command

    async def execute(self, request: BackendExecutionRequest, emit_event: EmitEvent) -> BackendExecutionResult:
        command = self.build_command(request)
        attempts = max(1, int(os.getenv("CODEX_EXEC_RETRIES", "2")))
        last: BackendExecutionResult | None = None
        for attempt in range(attempts):
            final_path = self._final_json_path(request)
            try:
                final_path.unlink()
            except FileNotFoundError:
                pass
            result = await self._execute_once(request, emit_event, command)
            last = result
            if result.status == "SUCCESS" or not self._is_retryable_failure(result):
                return result
            if attempt + 1 < attempts:
                await emit_event({"name": "backend.retry", "backend_type": AgentBackendType.CODEX_CLI.value, "reason": result.error or "retryable codex failure", "attempt": attempt + 1})
                await asyncio.sleep(2 * (attempt + 1))
        return last or BackendExecutionResult(status="FAILED", error="codex retry failed", backend_type=AgentBackendType.CODEX_CLI.value)

    async def _execute_once(self, request: BackendExecutionRequest, emit_event: EmitEvent, command: list[str]) -> BackendExecutionResult:
        env = os.environ.copy()
        api_key = os.getenv("CODEX_API_KEY") or os.getenv("OPENAI_API_KEY")
        if api_key:
            env["CODEX_API_KEY"] = api_key
        env["CODEX_HOME"] = str(self._prepare_codex_home(request))
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            cwd=str(request.workspace.workspace_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env=env,
        )
        self._processes[request.attempt_id] = process
        await emit_event({"name": "backend.started", "backend_type": AgentBackendType.CODEX_CLI.value, "backend_pid": process.pid})
        stdout_task = asyncio.create_task(self._consume_jsonl(process.stdout, emit_event))
        stderr_task = asyncio.create_task(self._consume_stderr(process.stderr))
        try:
            exit_code = await asyncio.wait_for(process.wait(), timeout=request.timeout_s)
        except (asyncio.TimeoutError, TimeoutError):
            await self._terminate_process_group(process)
            events = await stdout_task
            stderr = await stderr_task
            return BackendExecutionResult(
                status="TIMEOUT",
                error="codex timeout",
                backend_type=AgentBackendType.CODEX_CLI.value,
                backend_pid=process.pid,
                exit_code=None,
                usage=self._usage_from_events(events),
                artifacts=[self._stderr_artifact(request, stderr)] if stderr else [],
            )
        finally:
            self._processes.pop(request.attempt_id, None)

        events = await stdout_task
        stderr = await stderr_task
        artifacts = []
        if stderr:
            artifacts.append(self._stderr_artifact(request, stderr))
        final_output = self._read_final_json(request)
        status = "SUCCESS" if exit_code == 0 else "FAILED"
        return BackendExecutionResult(
            status=status,
            output=final_output,
            error="" if exit_code == 0 else (stderr or f"codex exited {exit_code}"),
            backend_type=AgentBackendType.CODEX_CLI.value,
            backend_pid=process.pid,
            backend_session_id=self._session_id(events),
            backend_run_id=f"run_{uuid4().hex}",
            exit_code=exit_code,
            usage=self._usage_from_events(events),
            artifacts=artifacts,
        )

    def _is_retryable_failure(self, result: BackendExecutionResult) -> bool:
        text = f"{result.output or ''}\n{result.error or ''}"
        return "stream disconnected before completion" in text or "Upstream request failed" in text

    async def cancel(self, attempt_id: str) -> None:
        process = self._processes.get(attempt_id)
        if process is not None:
            await self._terminate_process_group(process)

    async def cleanup(self, request: BackendExecutionRequest) -> None:
        return None

    def _build_prompt(self, request: BackendExecutionRequest) -> str:
        parts = []
        if request.system_prompt:
            parts.append(request.system_prompt)
        if request.user_message:
            parts.append(request.user_message)
        if request.task_input:
            parts.append("Task input JSON:\n" + json.dumps(request.task_input, ensure_ascii=False))
        if request.runtime_context:
            parts.append("Runtime context JSON:\n" + json.dumps(request.runtime_context, ensure_ascii=False))
        return "\n\n".join(parts)

    def _final_json_path(self, request: BackendExecutionRequest) -> Path:
        return self.artifact_store.attempt_dir(request.task_id, request.attempt_id) / "final.json"

    def _prepare_codex_home(self, request: BackendExecutionRequest) -> Path:
        target = self.artifact_store.attempt_dir(request.task_id, request.attempt_id) / "codex-home"
        target.mkdir(parents=True, exist_ok=True)
        source_home = Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex")))
        source_config = source_home / "config.toml"
        target_config = target / "config.toml"
        if source_config.exists() and not target_config.exists():
            shutil.copyfile(source_config, target_config)
        return target

    def _schema_path(self, raw_path: str) -> str:
        path = Path(raw_path)
        if path.is_absolute():
            return str(path)
        repo_root = Path(__file__).resolve().parents[2]
        candidate = (repo_root / path).resolve()
        return str(candidate)

    def _read_final_json(self, request: BackendExecutionRequest) -> str:
        path = self._final_json_path(request)
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
        return ""

    async def _consume_jsonl(self, stream, emit_event: EmitEvent) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if stream is None:
            return events
        while True:
            line = await stream.readline()
            if not line:
                break
            try:
                event = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                event = {"type": "invalid_jsonl"}
            clean = sanitize_codex_event(event)
            events.append(clean)
            await emit_event(clean)
        return events

    async def _consume_stderr(self, stream) -> str:
        if stream is None:
            return ""
        data = await stream.read()
        return data.decode("utf-8", errors="replace")[:65536]

    async def _terminate_process_group(self, process: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except asyncio.TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            await process.wait()

    def _usage_from_events(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        usage: dict[str, Any] = {"codex_events": len(events)}
        for event in reversed(events):
            event_usage = event.get("usage")
            if isinstance(event_usage, dict):
                usage.update(event_usage)
                break
        return usage

    def _session_id(self, events: list[dict[str, Any]]) -> str | None:
        for event in events:
            if event.get("name") == "backend.session.started":
                return event.get("thread_id")
        return None

    def _stderr_artifact(self, request: BackendExecutionRequest, stderr: str):
        return self.artifact_store.write_bytes(
            request.task_id,
            request.task_id,
            request.attempt_id,
            "log",
            "stderr.log",
            stderr.encode("utf-8", errors="replace"),
        )


def sanitize_codex_event(event: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("type") or "")
    mapped = {
        "thread.started": "backend.session.started",
        "turn.started": "agent.turn.started",
        "turn.completed": "agent.turn.completed",
        "turn.failed": "agent.turn.failed",
        "error": "backend.error",
    }.get(event_type, event_type or "backend.event")
    result: dict[str, Any] = {"name": mapped, "raw_type": event_type}
    if event.get("thread_id"):
        result["thread_id"] = str(event["thread_id"])
    if isinstance(event.get("usage"), dict):
        result["usage"] = event["usage"]
    item = event.get("item")
    if isinstance(item, dict):
        item_type = str(item.get("type") or "")
        result["item_type"] = item_type
        if item_type == "command_execution":
            result["name"] = "tool.command.started" if event_type == "item.started" else "tool.command.completed"
            command = item.get("command")
            if isinstance(command, list):
                result["command"] = " ".join(str(part) for part in command[:8])
            elif isinstance(command, str):
                result["command"] = command[:256]
        if "path" in item:
            result["path"] = str(item["path"])
            result["name"] = "artifact.file.changed"
    if event_type == "invalid_jsonl":
        result["name"] = "backend.error"
        result["error"] = "invalid jsonl"
    if event.get("message") and mapped == "backend.error":
        result["error"] = str(event["message"])[:512]
    return result
