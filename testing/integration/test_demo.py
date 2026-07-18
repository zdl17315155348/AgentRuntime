import json
import subprocess
from pathlib import Path


def _run_demo(mode: str) -> Path:
    root = Path("examples/production_incident_demo")
    proc = subprocess.run(["bash", str(root / "scripts" / f"run_{mode}.sh")], text=True, capture_output=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return root / "output" / "latest"


def _events(trace: dict) -> list[str]:
    names: list[str] = []
    for item in trace.values():
        names.extend(event["name"] for event in item.get("events", []))
    return names


def test_production_incident_demo_normal_runs():
    out = _run_demo("normal")
    metrics = json.loads((out / "metrics.json").read_text())
    attempts = json.loads((out / "attempts.json").read_text())
    dag = json.loads((out / "task_dag.json").read_text())
    trace = json.loads((out / "trace.json").read_text())
    report = json.loads((out / "final_report.md").read_text())

    assert metrics["agents"]["total"] >= 6
    assert metrics["resource"]["leases"] == []
    assert metrics["persistence"]["counts"]["processed_messages"] == 1
    assert dag["task_id"] == report["root_task_id"]
    assert len(dag["children"]) >= 12
    assert len(trace) >= 12
    assert all(item["trace_id"] for item in attempts)
    assert report["first_pytest_returncode"] != 0
    assert report["final_pytest_returncode"] == 0
    assert any(item["status"] in ("FAILED", "TIMEOUT") for item in attempts)
    assert any(item["status"] == "SUCCESS" for item in attempts)
    assert (out / "final.patch").exists()
    assert (out / "pytest.xml").read_text().strip()
    assert "agent_message_ack" in _events(trace)


def test_production_incident_demo_fault_uses_runtime_fallback():
    out = _run_demo("fault")
    metrics = json.loads((out / "metrics.json").read_text())
    attempts = json.loads((out / "attempts.json").read_text())
    trace = json.loads((out / "trace.json").read_text())
    report = json.loads((out / "final_report.md").read_text())
    t6_id = report["tasks"]["T6"]
    t6 = next(item for item in attempts if item["task_id"] == t6_id)
    event_names = _events(trace)

    assert t6["status"] == "SUCCESS"
    assert t6["definition"]["agent_name"] == "coder_a"
    assert any(attempt["agent_name"] == "coder_a" and attempt["status"] in ("FAILED", "TIMEOUT") for attempt in t6["attempts"])
    assert any(attempt["agent_name"] == "coder_b" and attempt["status"] == "SUCCESS" for attempt in t6["attempts"])
    assert "worker.lost" in event_names
    assert "task.fallback" in event_names
    assert next(item for item in attempts if item["task_id"] == report["tasks"]["T10"])["status"] == "SUCCESS"
    assert metrics["resource"]["leases"] == []
