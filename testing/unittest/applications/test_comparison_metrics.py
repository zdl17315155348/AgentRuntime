from __future__ import annotations

from testing.perf.comparison.metrics import summarize_metrics
from testing.perf.comparison.paired_runner import check_pair_fairness
from testing.perf.comparison.schemas import RunMetric


def test_summarize_metrics_excludes_warmup_and_counts_failures():
    rows = summarize_metrics(
        [
            RunMetric(benchmark_id="b", run_id="warm", mode="direct", concurrency=1, measured=False, success=True, total_ms=1),
            RunMetric(benchmark_id="b", run_id="r1", mode="direct", concurrency=1, measured=True, success=True, total_ms=10),
            RunMetric(benchmark_id="b", run_id="r2", mode="direct", concurrency=1, measured=True, success=False, total_ms=20),
        ]
    )

    assert rows[0]["sample_count"] == 2
    assert rows[0]["success_count"] == 1
    assert rows[0]["failure_count"] == 1
    assert rows[0]["mean"] == 15


def test_pair_fairness_rejects_mismatched_config():
    direct = {"run_id": "d", "pair_id": "p", "base_commit": "a", "prompt_hash": "h", "graph_version": "g", "codex_version": "c", "model": "m", "resource_limit": "r"}
    runtime = dict(direct, run_id="r", base_commit="b")

    result = check_pair_fairness(direct, runtime)

    assert result.comparable is False
    assert result.reason == "mismatch:base_commit"
