from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "target_repo"
TEMPLATE = ROOT / "target_repo_template"
OUTPUT = ROOT / "output" / "latest"
BASE_URL = os.getenv("AGENTD_BASE_URL", "http://127.0.0.1:8234")


AGENTS = {
    "architect": {"role": "architect", "capability": {"can_plan": True, "tools": ["repo_scan"]}},
    "coder_a": {"role": "coder", "capability": {"can_code": True, "tools": ["read_file", "write_file", "git_diff"]}},
    "coder_b": {"role": "coder", "capability": {"can_code": True, "tools": ["read_file", "write_file", "git_diff"]}},
    "tester": {"role": "tester", "capability": {"can_test": True, "tools": ["run_pytest"]}},
    "repair": {"role": "repair", "capability": {"can_code": True, "can_test": True, "tools": ["read_file", "write_file", "run_pytest"]}},
    "reviewer": {"role": "reviewer", "capability": {"can_review": True, "tools": ["git_diff", "run_pytest"]}},
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def run_git(*args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=TARGET,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")


def reset_repo() -> None:
    if TARGET.exists():
        shutil.rmtree(TARGET)

    shutil.copytree(TEMPLATE, TARGET)

    run_git("init")
    run_git("config", "user.name", "AgentRuntime Demo")
    run_git("config", "user.email", "demo@agentruntime.local")
    run_git("add", ".")
    run_git("commit", "-m", "demo baseline")
    (TARGET / "tests" / "test_security_regression.py").touch()
    run_git("add", "-N", "tests/test_security_regression.py")

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    print(f"demo target reset: {TARGET}")


def wait_agentd(client: httpx.Client) -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if client.get("/metrics").status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError("agentd not ready")


def register_agents(client: httpx.Client) -> None:
    for name, spec in AGENTS.items():
        payload = {
            "agent_name": name,
            "role": spec["role"],
            "capability": spec["capability"],
            "system_prompt": f"You are {name}.",
        }
        resp = client.post("/agents", json=payload)
        resp.raise_for_status()


def spawn(
    client: httpx.Client,
    root_task_id: str,
    agent_name: str,
    task_input: dict,
    dependencies: list[str] | None = None,
    failure_policy: dict | None = None,
    on_failure: dict[str, str] | None = None,
) -> dict:
    payload = {
        "agent_name": agent_name,
        "task_input": task_input,
        "dependencies": dependencies or [],
        "failure_policy": failure_policy or {"mode": "fail_open", "max_retries": 0, "timeout_ms": 3000},
    }
    if on_failure:
        payload["on_failure"] = on_failure
    resp = client.post(f"/tasks/{root_task_id}/spawn", json=payload)
    resp.raise_for_status()
    return resp.json()


def wait_task(client: httpx.Client, task_id: str, timeout_s: float = 120.0) -> dict:
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        data = client.get(f"/tasks/{task_id}").json()
        last = data
        if data["status"] in {"SUCCESS", "FAILED", "TIMEOUT", "CANCELLED"}:
            return data
        time.sleep(0.5)
    raise RuntimeError(f"{task_id}: {last}")


def task_trace(client: httpx.Client, task_id: str) -> dict:
    return client.get(f"/tasks/{task_id}/trace").json()


def task_output(task: dict) -> str:
    result = task.get("result") or {}
    output = str(result.get("output") or "")
    try:
        decoded = json.loads(output)
    except json.JSONDecodeError:
        return output
    if isinstance(decoded, str):
        return decoded
    return json.dumps(decoded, ensure_ascii=False)


def attempt_outputs(task: dict) -> str:
    parts: list[str] = []
    for attempt in task.get("attempts") or []:
        result = attempt.get("result") or {}
        output = result.get("output")
        if isinstance(output, str):
            parts.append(output)
    return "\n".join(parts)


def task_tool_metadata(task: dict) -> dict:
    usage = task.get("llm_usage") or {}
    metadata = usage.get("metadata") if isinstance(usage, dict) else {}
    return metadata if isinstance(metadata, dict) else {}


def update_auth(fix_expiration: bool) -> str:
    text = read(TARGET / "app" / "auth.py")
    text = text.replace(
        '    if user.password != password:\n        raise ValueError("bad password")\n',
        '    if user.password != password:\n        return None\n',
    )
    if fix_expiration:
        text = text.replace(
            'def decode_token(token: str):\n    payload = json.loads(base64.urlsafe_b64decode(token.encode()).decode())\n    return int(payload["sub"])\n',
            'def decode_token(token: str):\n    payload = json.loads(base64.urlsafe_b64decode(token.encode()).decode())\n    if int(payload.get("exp", 0)) < int(time.time()):\n        raise ValueError("token expired")\n    return int(payload["sub"])\n',
        )
    return text


def update_orders() -> str:
    return read(TARGET / "app" / "orders.py").replace(
        'def create_order(payload: OrderCreate, user: User, idempotency_key: str | None = None) -> Order:\n    order_id = database.next_order_id\n    database.next_order_id += 1\n    order = Order(id=order_id, user_id=user.id, item=payload.item, quantity=payload.quantity)\n    database.orders[order_id] = order\n    return order\n\n\ndef get_order(order_id: int, user: User) -> Order | None:\n    return database.orders.get(order_id)\n',
        'def create_order(payload: OrderCreate, user: User, idempotency_key: str | None = None) -> Order:\n    if idempotency_key and idempotency_key in database.idempotency_keys:\n        return database.orders[database.idempotency_keys[idempotency_key]]\n    order_id = database.next_order_id\n    database.next_order_id += 1\n    order = Order(id=order_id, user_id=user.id, item=payload.item, quantity=payload.quantity)\n    database.orders[order_id] = order\n    if idempotency_key:\n        database.idempotency_keys[idempotency_key] = order_id\n    return order\n\n\ndef get_order(order_id: int, user: User) -> Order | None:\n    order = database.orders.get(order_id)\n    if order is None or order.user_id != user.id:\n        return None\n    return order\n',
    )


def update_main() -> str:
    return read(TARGET / "app" / "main.py")


def security_regression_tests() -> str:
    return '''import pytest

from app.auth import create_token, decode_token, verify_password
from app.models import OrderCreate
from app.orders import create_order, get_order


def test_ownership_and_idempotency_and_expiration():
    alice = verify_password("alice", "alice-secret")
    bob = verify_password("bob", "bob-secret")
    assert get_order(1, bob) is None
    first = create_order(OrderCreate(item="chair", quantity=1), alice, idempotency_key="same-key")
    second = create_order(OrderCreate(item="chair", quantity=1), alice, idempotency_key="same-key")
    assert first.id == second.id
    expired = create_token(1, ttl_seconds=-1)
    with pytest.raises(ValueError):
        decode_token(expired)
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["normal", "fault"], default="normal")
    args = parser.parse_args()

    reset_repo()
    with httpx.Client(base_url=BASE_URL, timeout=30, trust_env=False) as client:
        wait_agentd(client)
        register_agents(client)
        traces: dict[str, dict] = {}

        root = client.post(
            "/tasks",
            json={
                "agent_name": "architect",
                "task_input": {"stage": "root"},
                "failure_policy": {"mode": "fail_open", "max_retries": 0, "timeout_ms": 3000},
            },
        ).json()
        root_task_id = root["task_id"]

        tasks: dict[str, dict] = {}
        tasks["T1"] = spawn(client, root_task_id, "architect", {"__tool": {"name": "repo_scan", "arguments": {}}})
        tasks["T2"] = spawn(client, root_task_id, "tester", {"__tool": {"name": "run_pytest", "arguments": {"args": ["tests"]}}}, [tasks["T1"]["task_id"]])
        tasks["T3"] = spawn(client, root_task_id, "reviewer", {"__tool": {"name": "git_diff", "arguments": {}}}, [tasks["T1"]["task_id"]])
        tasks["T4"] = spawn(client, root_task_id, "architect", {"stage": "plan"}, [tasks["T1"]["task_id"], tasks["T2"]["task_id"], tasks["T3"]["task_id"]])

        tasks["T5"] = spawn(client, root_task_id, "coder_a", {"__tool": {"name": "write_file", "arguments": {"path": "app/auth.py", "content": update_auth(False)}}}, [tasks["T4"]["task_id"]])
        tasks["T6"] = spawn(client, root_task_id, "coder_a", {"__test": {"crash_worker": args.mode == "fault"}, "__tool": {"name": "write_file", "arguments": {"path": "app/orders.py", "content": update_orders()}}}, [tasks["T4"]["task_id"]], {"mode": "fallback", "fallback_agent": "coder_b", "max_retries": 0, "timeout_ms": 3000})
        tasks["T7"] = spawn(client, root_task_id, "tester", {"__tool": {"name": "write_file", "arguments": {"path": "tests/test_security_regression.py", "content": security_regression_tests()}}}, [tasks["T4"]["task_id"]])
        tasks["T8"] = spawn(client, root_task_id, "tester", {"__tool": {"name": "run_pytest", "arguments": {"paths": ["tests", "../hidden_tests"], "junit_xml": str(OUTPUT / "integration_first.xml")}}}, [tasks["T5"]["task_id"], tasks["T6"]["task_id"], tasks["T7"]["task_id"]])
        t8 = wait_task(client, tasks["T8"]["task_id"])
        if t8["status"] == "SUCCESS":
            raise RuntimeError("first hidden test unexpectedly passed")
        first_output = f"{task_output(t8)}\n{attempt_outputs(t8)}\n{t8.get('error') or ''}"
        if "expir" not in first_output.lower() and "jwt" not in first_output.lower():
            raise RuntimeError("first hidden test did not expose JWT expiration")

        tasks["T9"] = spawn(
            client,
            root_task_id,
            "repair",
            {"__tool": {"name": "write_file", "arguments": {"path": "app/auth.py", "content": update_auth(True)}}},
            [tasks["T8"]["task_id"]],
            on_failure={tasks["T8"]["task_id"]: "fail_open"},
        )
        tasks["T10"] = spawn(client, root_task_id, "tester", {"__tool": {"name": "run_pytest", "arguments": {"paths": ["tests", "../hidden_tests"], "junit_xml": str(OUTPUT / "pytest.xml")}}}, [tasks["T9"]["task_id"]])
        tasks["T11"] = spawn(client, root_task_id, "reviewer", {"__tool": {"name": "git_diff", "arguments": {}}}, [tasks["T10"]["task_id"]])
        tasks["T12"] = spawn(client, root_task_id, "reviewer", {"__tool": {"name": "git_diff", "arguments": {}}}, [tasks["T11"]["task_id"]])

        message = client.post(
            "/messages",
            json={
                "from_agent": "reviewer",
                "to_agent": "tester",
                "payload": {"type": "review_notice", "message": "run final regression"},
            },
        ).json()
        message_id = message["message_id"]
        deadline = time.time() + 5
        while time.time() < deadline:
            processed = client.get("/metrics").json()["persistence"]["counts"]["processed_messages"]
            if processed == 1:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("agent message was not acked exactly once")

        final_tasks = {name: wait_task(client, info["task_id"]) for name, info in tasks.items()}
        first_metadata = task_tool_metadata(final_tasks["T8"])
        final_metadata = task_tool_metadata(final_tasks["T10"])
        if first_metadata.get("returncode") == 0:
            raise RuntimeError("first hidden test unexpectedly passed")
        if final_tasks["T10"]["status"] != "SUCCESS" or final_metadata.get("returncode") != 0:
            raise RuntimeError("final regression did not pass")
        for name, data in final_tasks.items():
            trace = task_trace(client, data["task_id"])
            if not trace:
                raise RuntimeError(f"missing trace for {name}")
            traces[name] = trace

        dag = client.get(f"/tasks/{root_task_id}/dag").json()
        metrics = client.get("/metrics").json()
        attempts = [client.get(f"/tasks/{info['task_id']}").json() for info in tasks.values()]
        patch = task_output(final_tasks["T12"])
        if not patch.strip():
            raise RuntimeError("final patch is empty")
        report = {
            "mode": args.mode,
            "root_task_id": root_task_id,
            "tasks": {name: info["task_id"] for name, info in tasks.items()},
            "first_pytest_returncode": first_metadata.get("returncode"),
            "final_pytest_returncode": final_metadata.get("returncode"),
            "message_id": message_id,
        }

    write(OUTPUT / "task_dag.json", json.dumps(dag, ensure_ascii=False, indent=2))
    write(OUTPUT / "trace.json", json.dumps(traces, ensure_ascii=False, indent=2))
    write(OUTPUT / "attempts.json", json.dumps(attempts, ensure_ascii=False, indent=2))
    write(OUTPUT / "metrics.json", json.dumps(metrics, ensure_ascii=False, indent=2))
    write(OUTPUT / "final.patch", patch)
    if not (OUTPUT / "pytest.xml").exists():
        write(OUTPUT / "pytest.xml", "")
    write(OUTPUT / "final_report.md", json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
