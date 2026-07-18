import json
import subprocess
from pathlib import Path


def test_production_incident_demo_normal_runs():
    root = Path("examples/production_incident_demo")
    proc = subprocess.run(["bash", str(root / "scripts" / "run_normal.sh")], text=True, capture_output=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = root / "output" / "latest"
    metrics = json.loads((out / "metrics.json").read_text())
    assert metrics["agents"] >= 6
    assert metrics["dynamic_subtasks"] >= 8
    assert metrics["first_integration_failed"] is True
    assert metrics["final_tests_passed"] is True
    assert (out / "task_dag.json").exists()
    assert (out / "trace.json").exists()
    assert (out / "final.patch").read_text()
