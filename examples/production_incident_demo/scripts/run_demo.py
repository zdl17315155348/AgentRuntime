from __future__ import annotations

import argparse
import difflib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "target_repo"
HIDDEN = ROOT / "hidden_tests"
OUTPUT = ROOT / "output" / "latest"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def event(trace: list[dict], event_type: str, task_id: str, agent: str, detail: dict | None = None) -> None:
    trace.append({
        "event_type": event_type,
        "task_id": task_id,
        "agent_name": agent,
        "timestamp": time.time(),
        "detail": detail or {},
    })


def run_pytest(paths: list[str], xml_name: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *paths, f"--junitxml={OUTPUT / xml_name}", "-q"],
        cwd=TARGET,
        text=True,
        capture_output=True,
        check=False,
    )


def patch_auth(fix_expiration: bool) -> None:
    path = TARGET / "app" / "auth.py"
    text = read(path)
    text = text.replace(
        '    if user.password != password:\n        raise ValueError("bad password")\n',
        '    if user.password != password:\n        return None\n',
    )
    if fix_expiration:
        text = text.replace(
            '    payload = json.loads(base64.urlsafe_b64decode(token.encode()).decode())\n    return int(payload["sub"])\n',
            '    payload = json.loads(base64.urlsafe_b64decode(token.encode()).decode())\n    if int(payload.get("exp", 0)) < int(time.time()):\n        raise ValueError("token expired")\n    return int(payload["sub"])\n',
        )
    write(path, text)


def patch_orders() -> None:
    path = TARGET / "app" / "orders.py"
    text = read(path)
    text = text.replace(
        'def create_order(payload: OrderCreate, user: User, idempotency_key: str | None = None) -> Order:\n    order_id = database.next_order_id\n',
        'def create_order(payload: OrderCreate, user: User, idempotency_key: str | None = None) -> Order:\n    if idempotency_key and idempotency_key in database.idempotency_keys:\n        return database.orders[database.idempotency_keys[idempotency_key]]\n    order_id = database.next_order_id\n',
    )
    text = text.replace(
        '    database.orders[order_id] = order\n    return order\n',
        '    database.orders[order_id] = order\n    if idempotency_key:\n        database.idempotency_keys[idempotency_key] = order_id\n    return order\n',
    )
    text = text.replace(
        'def get_order(order_id: int, user: User) -> Order | None:\n    return database.orders.get(order_id)\n',
        'def get_order(order_id: int, user: User) -> Order | None:\n    order = database.orders.get(order_id)\n    if order is None or order.user_id != user.id:\n        return None\n    return order\n',
    )
    write(path, text)


def patch_main() -> None:
    path = TARGET / "app" / "main.py"
    text = read(path)
    text = text.replace(
        '    user_id = decode_token(authorization.removeprefix("Bearer "))\n',
        '    try:\n        user_id = decode_token(authorization.removeprefix("Bearer "))\n    except Exception:\n        raise HTTPException(status_code=401, detail="invalid token")\n',
    )
    write(path, text)


def add_tests() -> None:
    write(TARGET / "tests" / "test_security_regression.py", '''import pytest

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
''')


def collect_patch(before: dict[str, str]) -> str:
    parts: list[str] = []
    for path in sorted(TARGET.rglob("*.py")):
        rel = path.relative_to(TARGET)
        old = before.get(str(rel), "")
        new = read(path)
        if old != new:
            parts.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile=f"a/{rel}", tofile=f"b/{rel}"))
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["normal", "fault"], default="normal")
    args = parser.parse_args()
    template = ROOT / "target_repo_template"
    if template.exists():
        if TARGET.exists():
            shutil.rmtree(TARGET)
        shutil.copytree(template, TARGET)
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)

    before = {str(path.relative_to(TARGET)): read(path) for path in TARGET.rglob("*.py")}
    trace: list[dict] = []
    dag = {"root": "R0", "tasks": [], "edges": []}
    attempts = []
    agents = ["architect", "coder_a", "coder_b", "tester", "repair", "reviewer"]

    def add_task(task_id: str, agent: str, deps: list[str] | None = None) -> None:
        dag["tasks"].append({"task_id": task_id, "agent": agent, "dependencies": deps or []})
        for dep in deps or []:
            dag["edges"].append({"from": dep, "to": task_id})
        event(trace, "task.spawn", task_id, agent, {"dependencies": deps or []})

    add_task("T1_scan", "architect")
    add_task("T2_public_baseline", "tester")
    add_task("T3_security_audit", "reviewer")
    baseline = run_pytest(["tests"], "baseline.xml")
    event(trace, "tool.finish", "T2_public_baseline", "tester", {"returncode": baseline.returncode})
    add_task("T4_plan", "architect", ["T1_scan", "T2_public_baseline", "T3_security_audit"])
    add_task("T5_login_fix", "coder_a", ["T4_plan"])
    add_task("T6_order_owner_fix", "coder_a", ["T4_plan"])
    add_task("T7_idempotency_fix", "coder_a", ["T4_plan"])
    add_task("T8_test_generation", "tester", ["T4_plan"])

    attempts.append({"task_id": "T6_order_owner_fix", "attempt_id": "T6_order_owner_fix:attempt:1", "agent": "coder_a", "status": "FAILED" if args.mode == "fault" else "SUCCESS"})
    if args.mode == "fault":
        event(trace, "worker.lost", "T6_order_owner_fix", "coder_a")
        event(trace, "task.fallback", "T6_order_owner_fix", "coder_b")
        attempts.append({"task_id": "T6_order_owner_fix", "attempt_id": "T6_order_owner_fix:attempt:2", "agent": "coder_b", "status": "SUCCESS"})

    patch_auth(fix_expiration=False)
    patch_orders()
    patch_main()
    add_task("T9_integration_test", "tester", ["T5_login_fix", "T6_order_owner_fix", "T7_idempotency_fix", "T8_test_generation"])
    first_hidden = run_pytest(["tests", str(HIDDEN)], "integration_first.xml")
    event(trace, "tool.finish", "T9_integration_test", "tester", {"returncode": first_hidden.returncode})
    add_task("T10_repair_jwt", "repair", ["T9_integration_test"])
    patch_auth(fix_expiration=True)
    add_tests()
    retry = run_pytest(["tests", str(HIDDEN)], "pytest.xml")
    event(trace, "tool.finish", "T10_repair_jwt", "repair", {"returncode": retry.returncode})
    add_task("T11_review", "reviewer", ["T10_repair_jwt"])
    add_task("T12_release", "reviewer", ["T11_review"])

    final_patch = collect_patch(before)
    write(OUTPUT / "task_dag.json", json.dumps(dag, ensure_ascii=False, indent=2))
    write(OUTPUT / "trace.json", json.dumps(trace, ensure_ascii=False, indent=2))
    write(OUTPUT / "attempts.json", json.dumps(attempts, ensure_ascii=False, indent=2))
    metrics = {
        "mode": args.mode,
        "agents": len(agents),
        "dynamic_subtasks": len(dag["tasks"]),
        "parallel_groups": [["T1_scan", "T2_public_baseline", "T3_security_audit"], ["T5_login_fix", "T6_order_owner_fix", "T7_idempotency_fix", "T8_test_generation"]],
        "repair_task_created": True,
        "fallback": args.mode == "fault",
        "baseline_failed": baseline.returncode != 0,
        "first_integration_failed": first_hidden.returncode != 0,
        "final_tests_passed": retry.returncode == 0,
    }
    write(OUTPUT / "metrics.json", json.dumps(metrics, ensure_ascii=False, indent=2))
    write(OUTPUT / "final.patch", final_patch)
    write(OUTPUT / "final_report.md", "\n".join([
        "# Production Incident Demo Report",
        f"- mode: {args.mode}",
        f"- agents: {len(agents)}",
        f"- dynamic_subtasks: {len(dag['tasks'])}",
        f"- first_integration_failed: {first_hidden.returncode != 0}",
        f"- final_tests_passed: {retry.returncode == 0}",
    ]))
    return 0 if retry.returncode == 0 and first_hidden.returncode != 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
