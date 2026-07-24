from __future__ import annotations

import pytest

from testing.perf.comparison.runner import (
    _matches_fault_trigger,
    compute_prompt_hash,
    prepare_runtime_benchmark_agents,
    require_clean_source_tree,
    run_matrix,
    run_matrix_detailed,
    write_benchmark_outputs,
)
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


def test_runtime_benchmark_registers_and_validates_demo_agents(monkeypatch):
    config = BenchmarkConfig(
        benchmark_id="bench_register",
        task_case="incident_repair_v1",
        modes=["runtime"],
        concurrency_levels=[1],
        warmup_runs=0,
        measured_runs=1,
        cpu_limit=1,
        memory_limit_mb=512,
        deepseek_model="deepseek-chat",
        base_commit="HEAD",
        prompt_hash="p",
        graph_version="incident_repair_v1",
    )
    created = []

    class _Client:
        def __init__(self, base_url):
            self.base_url = base_url

        def get_metrics(self):
            return {"runtime_config": {"llm_backend": "deepseek", "llm_api_key_present": True}}

        def create_agent(self, **kwargs):
            created.append(kwargs)
            return {"ok": True}

        def list_agents(self):
            return {
                "agents": [
                    {"name": call["agent_name"], "status": "READY", "backend": call["backend"], "failure_policy": call.get("failure_policy") or {}}
                    for call in created
                ]
            }

    monkeypatch.setattr("testing.perf.comparison.runner.AgentRuntimeClient", _Client)

    registration = prepare_runtime_benchmark_agents(config, base_url="http://agentd")

    assert registration["required"] is True
    assert registration["llm_backend"] == "deepseek"
    assert registration["agents"]["reviewer"]["backend"]["sandbox"] == "read-only"
    assert {call["agent_name"] for call in created} == {"architect", "coder_a", "coder_b", "tester", "repair", "reviewer"}


def test_runtime_benchmark_rejects_mock_agentd(monkeypatch):
    config = BenchmarkConfig(
        benchmark_id="bench_register_mock",
        task_case="incident_repair_v1",
        modes=["runtime"],
        concurrency_levels=[1],
        warmup_runs=0,
        measured_runs=1,
        cpu_limit=1,
        memory_limit_mb=512,
        deepseek_model="deepseek-chat",
        base_commit="HEAD",
        prompt_hash="p",
        graph_version="incident_repair_v1",
    )

    class _Client:
        def __init__(self, base_url):
            pass

        def get_metrics(self):
            return {"runtime_config": {"llm_backend": "mock", "llm_api_key_present": False}}

    monkeypatch.setattr("testing.perf.comparison.runner.AgentRuntimeClient", _Client)

    with pytest.raises(RuntimeError, match="llm_backend != mock"):
        prepare_runtime_benchmark_agents(config)


@pytest.mark.anyio
async def test_comparison_runner_smoke_records_experiment_scenarios(tmp_path):
    pytest.importorskip("langgraph")
    for experiment, kwargs in [
        ("baseline", {}),
        ("fault_recovery", {"direct_retry_enabled": True, "runtime_fault_enabled": True}),
        ("recovery_context", {"recovery_context_enabled": False}),
    ]:
        config = BenchmarkConfig(
            benchmark_id=f"bench_{experiment}",
            task_case="incident_repair_v1",
            modes=["direct", "runtime"],
            concurrency_levels=[1],
            warmup_runs=0,
            measured_runs=1,
            cpu_limit=1,
            memory_limit_mb=512,
            deepseek_model="deepseek-chat",
            base_commit="HEAD",
            prompt_hash="p",
            graph_version="incident_repair_v1",
            experiment=experiment,
            **kwargs,
        )

        workflows, trials = await run_matrix_detailed(config, "/data1/projects/agent-runtime-os", smoke=True)
        metrics = await run_matrix(config, "/data1/projects/agent-runtime-os", smoke=True)
        out = write_benchmark_outputs(config, metrics, tmp_path, workflow_metrics=workflows, trial_metrics=trials)
        report = (out / "report.json").read_text(encoding="utf-8")

        assert f'"experiment": "{experiment}"' in report
        assert all(item.experiment == experiment for item in workflows)
        if experiment == "recovery_context":
            assert '"recovery_context_enabled": false' in report


def test_runtime_fault_trigger_matches_backend_started_agent():
    config = BenchmarkConfig(
        benchmark_id="bench_fault_event",
        task_case="incident_repair_v1",
        modes=["runtime"],
        concurrency_levels=[1],
        warmup_runs=0,
        measured_runs=1,
        cpu_limit=1,
        memory_limit_mb=512,
        deepseek_model="deepseek-chat",
        base_commit="HEAD",
        prompt_hash="p",
        graph_version="incident_repair_v1",
        experiment="fault_recovery",
        runtime_fault_enabled=True,
        fault_target_agent="coder_a",
        fault_trigger="backend.started",
    )

    assert _matches_fault_trigger("http://agentd", {"name": "backend.started", "data": {"agent_name": "coder_a"}}, config)
    assert not _matches_fault_trigger("http://agentd", {"name": "backend.started", "data": {"agent_name": "coder_b"}}, config)
