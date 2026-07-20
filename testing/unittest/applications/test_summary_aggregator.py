from __future__ import annotations

from applications.incident_repair.config import ExecutionMode, IncidentRunConfig
from applications.incident_repair.services.summary_aggregator import RunSummaryAggregator


def test_summary_aggregator_uses_execution_records_and_result_fields():
    config = IncidentRunConfig(execution_mode=ExecutionMode.DIRECT, run_id="run", thread_id="thread", source_repo=".", base_commit="HEAD")
    summary = RunSummaryAggregator().build(
        config,
        {
            "workflow_status": "SUCCESS",
            "repair_round": 1,
            "patch_refs": [{"patch_path": "x"}],
            "integration_result": {"changed_files": ["app.py"]},
            "test_summary": {"returncode": 0, "passed": 3, "failed": 0},
            "review_summary": {"approved": True},
        },
        [{"name": "graph.run.started"}],
        [
            {
                "status": "SUCCESS",
                "attempt_ids": ["a1"],
                "queue_wait_ms": 2,
                "setup_ms": 3,
                "backend_ms": 4,
                "cleanup_ms": 5,
                "total_tokens": 6,
                "peak_rss_mb": 7,
                "cpu_time_ms": 8,
            }
        ],
    )

    assert summary["execution"]["tasks"] == 1
    assert summary["execution"]["attempts"] == 1
    assert summary["execution"]["backend_ms"] == 4
    assert summary["resources"]["peak_rss_mb"] == 7
    assert summary["result"]["patch_non_empty"] is True
    assert summary["result"]["tests_passed"] == 3
