from __future__ import annotations

import pytest

from testing.perf.comparison.runner import compute_prompt_hash, run_matrix, run_matrix_detailed, write_benchmark_outputs
from testing.perf.comparison.schemas import BenchmarkConfig


@pytest.mark.anyio
async def test_comparison_runner_smoke_writes_raw_and_summary(tmp_path):
    pytest.importorskip("langgraph")
    config = BenchmarkConfig(
        benchmark_id="bench_test",
        task_case="incident_repair_v1",
        modes=["direct", "runtime"],
        concurrency_levels=[1],
        warmup_runs=1,
        measured_runs=2,
        cpu_limit=1,
        memory_limit_mb=512,
        deepseek_model="deepseek-chat",
        base_commit="HEAD",
        prompt_hash="p",
        graph_version="incident_repair_v1",
    )

    metrics = await run_matrix(config, "/data1/projects/agent-runtime-os", smoke=True)
    out = write_benchmark_outputs(config, metrics, tmp_path)

    assert len(metrics) == 6
    assert (out / "raw_runs.csv").exists()
    assert (out / "paired_runs.csv").exists()
    assert (out / "report.json").exists()
    summary = (out / "summary.csv").read_text(encoding="utf-8")
    assert "success_count" in summary
    assert "direct" in summary
    assert "runtime" in summary
    pairs = (out / "paired_runs.csv").read_text(encoding="utf-8")
    assert "direct_run_id" in pairs
    assert "runtime_run_id" in pairs


@pytest.mark.anyio
async def test_comparison_runner_starts_concurrent_workflows_in_trial(tmp_path):
    pytest.importorskip("langgraph")
    config = BenchmarkConfig(
        benchmark_id="bench_trial",
        task_case="incident_repair_v1",
        modes=["direct"],
        concurrency_levels=[2],
        warmup_runs=0,
        measured_runs=1,
        cpu_limit=1,
        memory_limit_mb=512,
        deepseek_model="deepseek-chat",
        base_commit="HEAD",
        prompt_hash="p",
        graph_version="incident_repair_v1",
        data_kind="synthetic_smoke",
        performance_claim_allowed=False,
    )

    workflows, trials = await run_matrix_detailed(config, "/data1/projects/agent-runtime-os", smoke=True)

    assert len(workflows) == 2
    assert len(trials) == 1
    assert trials[0].concurrency == 2
    assert trials[0].success_count == 2


def test_prompt_hash_is_non_empty():
    assert compute_prompt_hash()
