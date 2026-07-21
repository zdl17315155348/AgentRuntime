from __future__ import annotations

import pytest

from testing.perf.comparison.runner import compute_prompt_hash, require_clean_source_tree, run_matrix, run_matrix_detailed, write_benchmark_outputs
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
    assert {metric.pair_id for metric in metrics if metric.measured} == {"c1_1", "c1_2"}
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
    report = (out / "report.json").read_text(encoding="utf-8")
    assert '"all_pairs_comparable": true' in report


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


@pytest.mark.anyio
async def test_comparison_runner_interleaves_direct_runtime_pairs():
    pytest.importorskip("langgraph")
    config = BenchmarkConfig(
        benchmark_id="bench_pair_order",
        task_case="incident_repair_v1",
        modes=["direct", "runtime"],
        concurrency_levels=[1],
        warmup_runs=0,
        measured_runs=3,
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

    assert [trial.mode for trial in trials] == ["direct", "runtime", "runtime", "direct", "direct", "runtime"]
    assert [trial.pair_id for trial in trials] == ["c1_0", "c1_0", "c1_1", "c1_1", "c1_2", "c1_2"]
    assert {workflow.pair_id for workflow in workflows} == {"c1_0", "c1_1", "c1_2"}


def test_require_clean_source_tree_rejects_tracked_changes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "AgentRuntime"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "runtime@local"], cwd=repo, check=True)
    tracked = repo / "tracked.txt"
    tracked.write_text("ok\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
    tracked.write_text("dirty\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="formal benchmark requires"):
        require_clean_source_tree(repo)


def test_prompt_hash_is_non_empty():
    assert compute_prompt_hash()
