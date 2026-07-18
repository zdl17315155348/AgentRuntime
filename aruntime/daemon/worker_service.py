import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_log_handles: dict[str, tuple[Any, Any]] = {}

def log_dir() -> str:
    path = os.getenv("AGENTD_LOG_DIR", os.path.join("/tmp", "agent-runtime-os", "logs"))
    Path(path).mkdir(parents=True, exist_ok=True)
    return path


def json_log(event: str, **fields: Any) -> None:
    line = {"ts": datetime.now().isoformat(), "event": event, **fields}
    path = os.path.join(log_dir(), "agentd.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def start_worker_process(agent_name: str, uds_path: str, llm_backend: str, llm_api_key: str, auth_token: str, workspace_root: str | None = None) -> subprocess.Popen:
    env = os.environ.copy()
    env["AGENT_NAME"] = agent_name
    env["AGENTD_UDS_PATH"] = uds_path
    env["AGENT_AUTH_TOKEN"] = auth_token
    env["LLM_BACKEND"] = llm_backend
    env["LLM_API_KEY"] = llm_api_key or ""
    if workspace_root:
        env["AGENT_WORKSPACE"] = workspace_root
    logs = log_dir()
    stdout_path = os.path.join(logs, f"{agent_name}.stdout.log")
    stderr_path = os.path.join(logs, f"{agent_name}.stderr.log")
    stdout = open(stdout_path, "ab")
    stderr = open(stderr_path, "ab")
    _log_handles[agent_name] = (stdout, stderr)
    proc = subprocess.Popen(
        [sys.executable, "-m", "aruntime.worker.agent_worker"],
        cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
        env=env,
        stdout=stdout,
        stderr=stderr,
    )
    json_log("worker.started", agent_name=agent_name, pid=proc.pid, stdout=stdout_path, stderr=stderr_path)
    return proc
