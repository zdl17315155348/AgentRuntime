from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from applications.incident_repair.config import ExecutionMode, IncidentRunConfig
from applications.incident_repair.execution.base import AgentExecutionRequest, AgentExecutionResult, ExecutionMetrics, ExecutionProvider
from applications.incident_repair.services.run_service import IncidentRunService
from testing.perf.comparison.metrics import summarize_metrics
from testing.perf.comparison.schemas import BenchmarkConfig, PairedRun, RunMetric, TrialMetric, WorkflowMetric


def write_benchmark_outputs(config: BenchmarkConfig, metrics: list[RunMetric], root: str | Path = "run-data/benchmarks", workflow_metrics: list[WorkflowMetric] | None = None, trial_metrics: list[TrialMetric] | None = None) -> Path:
    out = Path(root) / config.benchmark_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")
    with (out / "raw_runs.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(RunMetric.model_fields))
        writer.writeheader()
        for metric in metrics:
            writer.writerow(metric.model_dump())
    workflow_metrics = workflow_metrics or [
        WorkflowMetric(
            trial_id=metric.run_id,
            workflow_index=0,
            benchmark_id=metric.benchmark_id,
            run_id=metric.run_id,
            mode=metric.mode,
            concurrency=metric.concurrency,
            measured=metric.measured,
            latency_ms=metric.total_ms,
            success=metric.success,
            queue_wait_ms=metric.queue_wait_ms,
            backend_ms=metric.backend_ms,
            peak_rss_mb=metric.peak_rss_mb,
            error=metric.error,
        )
        for metric in metrics
    ]
    trial_metrics = trial_metrics or []
    with (out / "workflow_runs.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(WorkflowMetric.model_fields))
        writer.writeheader()
        for metric in workflow_metrics:
            writer.writerow(metric.model_dump())
    with (out / "trial_runs.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(TrialMetric.model_fields))
        writer.writeheader()
        for metric in trial_metrics:
            writer.writerow(metric.model_dump())
    summary = summarize_metrics(metrics)
    with (out / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
        fieldnames = list(summary[0].keys()) if summary else ["mode", "concurrency"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary)
    pairs = build_measured_pairs(metrics)
    with (out / "paired_runs.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(PairedRun.model_fields))
        writer.writeheader()
        for pair in pairs:
            writer.writerow(pair.model_dump())
    report = {
        "benchmark_id": config.benchmark_id,
        "task_case": config.task_case,
        "warmup_runs": config.warmup_runs,
        "measured_runs": config.measured_runs,
        "rows": len(metrics),
        "measured_rows": sum(1 for item in metrics if item.measured),
        "summary": summary,
        "pairs": [pair.model_dump() for pair in pairs],
        "data_kind": config.data_kind,
        "performance_claim_allowed": config.performance_claim_allowed,
        "prompt_hash": config.prompt_hash,
    }
    (out / "comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out


def build_measured_pairs(metrics: list[RunMetric]) -> list[PairedRun]:
    pairs: list[PairedRun] = []
    direct_by_concurrency: dict[int, list[RunMetric]] = {}
    runtime_by_concurrency: dict[int, list[RunMetric]] = {}
    for metric in metrics:
        if not metric.measured:
            continue
        if metric.mode == "direct":
            direct_by_concurrency.setdefault(metric.concurrency, []).append(metric)
        elif metric.mode == "runtime":
            runtime_by_concurrency.setdefault(metric.concurrency, []).append(metric)
    for concurrency, direct_items in sorted(direct_by_concurrency.items()):
        runtime_items = runtime_by_concurrency.get(concurrency, [])
        for index, direct in enumerate(direct_items):
            runtime = runtime_items[index] if index < len(runtime_items) else None
            pairs.append(
                PairedRun(
                    pair_id=f"c{concurrency}_{index}",
                    direct_run_id=direct.run_id,
                    runtime_run_id=runtime.run_id if runtime else "",
                    comparable=runtime is not None,
                    reason="" if runtime is not None else "missing:runtime",
                )
            )
    return pairs


class SmokeBenchmarkProvider(ExecutionProvider):
    @property
    def mode(self) -> str:
        return "smoke"

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        metrics = ExecutionMetrics(submit_started_at=time.perf_counter(), execution_started_at=time.perf_counter(), execution_finished_at=time.perf_counter(), total_ms=1)
        if request.role == "planner":
            return AgentExecutionResult(
                status="SUCCESS",
                structured_result={"version": "1.0", "summary": "smoke", "tasks": [{"local_id": "coder", "role": "coder", "goal": request.goal, "dependencies": []}]},
                metrics=metrics,
            )
        if request.role == "coder":
            return AgentExecutionResult(status="SUCCESS", patch_ref={"task_local_id": "coder", "artifact_id": None, "patch_path": "/tmp/smoke.patch", "sha256": "smoke", "changed_files": ["app.py"]}, metrics=metrics)
        if request.role == "tester":
            return AgentExecutionResult(status="SUCCESS", structured_result={"returncode": 0, "passed": 1, "failed": 0, "failed_tests": [], "report_artifact_id": None}, metrics=metrics)
        if request.role == "reviewer":
            return AgentExecutionResult(status="SUCCESS", structured_result={"approved": True, "requirements_covered": ["smoke"], "issues": [], "summary": "ok", "artifact_id": None}, metrics=metrics)
        return AgentExecutionResult(status="SUCCESS", structured_result={}, metrics=metrics)

    async def cancel_run(self, run_id: str) -> None:
        return None

    async def inject_fault(self, run_id: str, target: dict) -> dict:
        return {}

    async def get_execution_snapshot(self, run_id: str) -> dict:
        return {}


async def run_one_workflow(service: IncidentRunService, config: BenchmarkConfig, source_repo: str, mode: str, concurrency: int, measured: bool, workflow_index: int, smoke: bool, trial_id: str) -> WorkflowMetric:
    run_id = f"bench_{uuid4().hex}"
    started = time.perf_counter()
    run_config = IncidentRunConfig(
        execution_mode=ExecutionMode.DIRECT if smoke else ExecutionMode(mode),
        run_id=run_id,
        thread_id=f"thread_{run_id}",
        source_repo=source_repo,
        base_commit=config.base_commit or "HEAD",
        max_concurrency=concurrency,
        deepseek_model=config.deepseek_model,
        codex_model=config.codex_model,
        cpu_limit=config.cpu_limit,
        memory_limit_mb=config.memory_limit_mb,
        benchmark_id=config.benchmark_id,
    )
    dependencies = {"provider": SmokeBenchmarkProvider(), "integration_service": _SmokeIntegration()} if smoke else {}
    try:
        result = await service.execute_run(run_config, "修复认证、JWT和订单安全问题", dependencies)
        success = result["summary"]["status"] == "SUCCESS"
        error = str(result["summary"].get("error") or "")
        execution = result["summary"].get("execution") or {}
        resources = result["summary"].get("resources") or {}
    except Exception as exc:
        success = False
        error = str(exc)
        execution = {}
        resources = {}
    return WorkflowMetric(
        trial_id=trial_id,
        workflow_index=workflow_index,
        benchmark_id=config.benchmark_id,
        run_id=run_id,
        mode=mode,
        concurrency=concurrency,
        measured=measured,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
        success=success,
        queue_wait_ms=float(execution.get("queue_wait_ms") or 0),
        backend_ms=float(execution.get("backend_ms") or 0),
        peak_rss_mb=float(resources.get("peak_rss_mb") or 0),
        error=error,
    )


async def run_trial(config: BenchmarkConfig, source_repo: str, mode: str, concurrency: int, measured: bool, smoke: bool, trial_index: int) -> tuple[list[WorkflowMetric], TrialMetric]:
    service = IncidentRunService()
    trial_id = f"{mode}_c{concurrency}_{trial_index}_{uuid4().hex[:8]}"
    started = time.perf_counter()
    runs = await asyncio.gather(
        *[run_one_workflow(service, config, source_repo, mode, concurrency, measured, index, smoke, trial_id) for index in range(concurrency)],
        return_exceptions=False,
    )
    makespan_ms = round((time.perf_counter() - started) * 1000, 3)
    success_count = sum(1 for run in runs if run.success)
    trial = TrialMetric(
        trial_id=trial_id,
        benchmark_id=config.benchmark_id,
        mode=mode,
        concurrency=concurrency,
        measured=measured,
        batch_makespan_ms=makespan_ms,
        throughput_per_min=round((success_count / makespan_ms) * 60000, 6) if makespan_ms > 0 else 0,
        success_count=success_count,
        failure_count=len(runs) - success_count,
        peak_rss_mb=max([run.peak_rss_mb for run in runs] or [0]),
    )
    return runs, trial


async def run_matrix(config: BenchmarkConfig, source_repo: str, smoke: bool = False, fake: bool | None = None) -> list[RunMetric]:
    if fake is not None:
        smoke = fake
    _ensure_git_safe_directory(source_repo)
    workflow_metrics, _trial_metrics = await run_matrix_detailed(config, source_repo, smoke=smoke)
    return [
        RunMetric(
            benchmark_id=item.benchmark_id,
            run_id=item.run_id,
            mode=item.mode,
            concurrency=item.concurrency,
            measured=item.measured,
            success=item.success,
            total_ms=item.latency_ms,
            queue_wait_ms=item.queue_wait_ms,
            backend_ms=item.backend_ms,
            peak_rss_mb=item.peak_rss_mb,
            error=item.error,
        )
        for item in workflow_metrics
    ]


async def run_matrix_detailed(config: BenchmarkConfig, source_repo: str, smoke: bool = False) -> tuple[list[WorkflowMetric], list[TrialMetric]]:
    _ensure_git_safe_directory(source_repo)
    workflow_metrics: list[WorkflowMetric] = []
    trial_metrics: list[TrialMetric] = []
    for mode in config.modes:
        for concurrency in config.concurrency_levels:
            total_runs = config.warmup_runs + config.measured_runs
            for index in range(total_runs):
                measured = index >= config.warmup_runs
                workflows, trial = await run_trial(config, source_repo, mode, concurrency, measured, smoke, index)
                workflow_metrics.extend(workflows)
                trial_metrics.append(trial)
    return workflow_metrics, trial_metrics


class _SmokeIntegration:
    def integrate(self, source_repo, base_commit, patch_refs, run_id, repair_round):
        return type(
            "Result",
            (),
            {
                "status": "SUCCESS",
                "workspace_path": source_repo,
                "base_commit": base_commit,
                "integrated_commit": base_commit,
                "applied_artifact_ids": [str(ref.get("artifact_id") or "") for ref in patch_refs],
                "changed_files": ["app.py"],
                "conflict_files": [],
                "error": None,
            },
        )()


def _ensure_git_safe_directory(source_repo: str) -> None:
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", str(Path(source_repo).resolve())], capture_output=True, text=True, check=False, timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-case", required=True)
    parser.add_argument("--modes", required=True)
    parser.add_argument("--concurrency", required=True)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--cpu-limit", type=float, default=4)
    parser.add_argument("--memory-limit-mb", type=int, default=4096)
    parser.add_argument("--source-repo", default="examples/production_incident_demo/target_repo")
    parser.add_argument("--base-commit", default="HEAD")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--fake", action="store_true", help="deprecated alias for --smoke")
    args = parser.parse_args()
    smoke = bool(args.smoke or args.fake)
    config = BenchmarkConfig(
        benchmark_id=f"{args.task_case}_comparison",
        task_case=args.task_case,
        modes=args.modes.split(","),
        concurrency_levels=[int(item) for item in args.concurrency.split(",")],
        warmup_runs=args.warmup,
        measured_runs=args.runs,
        cpu_limit=args.cpu_limit,
        memory_limit_mb=args.memory_limit_mb,
        deepseek_model="deepseek-chat",
        base_commit=args.base_commit,
        prompt_hash=compute_prompt_hash(),
        graph_version="incident_repair_v1",
        data_kind="synthetic_smoke" if smoke else "real_agent",
        performance_claim_allowed=not smoke,
    )
    workflows, trials = asyncio.run(run_matrix_detailed(config, args.source_repo, smoke))
    metrics = [
        RunMetric(
            benchmark_id=item.benchmark_id,
            run_id=item.run_id,
            mode=item.mode,
            concurrency=item.concurrency,
            measured=item.measured,
            success=item.success,
            total_ms=item.latency_ms,
            queue_wait_ms=item.queue_wait_ms,
            backend_ms=item.backend_ms,
            peak_rss_mb=item.peak_rss_mb,
            error=item.error,
        )
        for item in workflows
    ]
    write_benchmark_outputs(config, metrics, workflow_metrics=workflows, trial_metrics=trials)
    print(f"wrote run-data/benchmarks/{config.benchmark_id}")


def compute_prompt_hash(root: str | Path = ".") -> str:
    root = Path(root)
    files = [
        "applications/incident_repair/prompts/planner.md",
        "applications/incident_repair/prompts/coder.md",
        "applications/incident_repair/prompts/repair.md",
        "applications/incident_repair/prompts/reviewer.md",
        "configs/schemas/planner_inspection.schema.json",
        "configs/schemas/planner_plan.schema.json",
        "configs/schemas/codex_coder_result.schema.json",
        "configs/schemas/codex_reviewer_result.schema.json",
    ]
    digest = hashlib.sha256()
    for rel in files:
        path = root / rel
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()


if __name__ == "__main__":
    main()
