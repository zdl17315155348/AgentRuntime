import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from aruntime.core.models import AgentSpec

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


def start_worker_process(
    agent: AgentSpec | str,
    uds_path: str,
    auth_token: str,
    llm_backend: str = "mock",
    llm_api_key: str = "",
) -> subprocess.Popen:
    if isinstance(agent, AgentSpec):
        agent_name = agent.agent_name
        agent_spec_json = agent.model_dump_json()
    else:
        agent_name = str(agent)
        agent_spec_json = ""
    env = os.environ.copy()
    env["AGENT_NAME"] = agent_name
    if agent_spec_json:
        env["AGENT_SPEC_JSON"] = agent_spec_json
    env["AGENTD_UDS_PATH"] = uds_path
    env["AGENT_AUTH_TOKEN"] = auth_token
    env["LLM_BACKEND"] = llm_backend
    env["LLM_API_KEY"] = llm_api_key or ""
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
        start_new_session=True,
    )
    json_log("worker.started", agent_name=agent_name, pid=proc.pid, stdout=stdout_path, stderr=stderr_path)
    return proc
