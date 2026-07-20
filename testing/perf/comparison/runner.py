from __future__ import annotations

import argparse
import asyncio
import csv
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from applications.incident_repair.config import ExecutionMode, IncidentRunConfig
from applications.incident_repair.execution.base import AgentExecutionRequest, AgentExecutionResult, ExecutionMetrics, ExecutionProvider
from applications.incident_repair.services.run_service import IncidentRunService
from testing.perf.comparison.metrics import summarize_metrics
from testing.perf.comparison.schemas import BenchmarkConfig, PairedRun, RunMetric


def write_benchmark_outputs(config: BenchmarkConfig, metrics: list[RunMetric], root: str | Path = "run-data/benchmarks") -> Path:
    out = Path(root) / config.benchmark_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")
    with (out / "raw_runs.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(RunMetric.model_fields))
        writer.writeheader()
        for metric in metrics:
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


class FakeBenchmarkProvider(ExecutionProvider):
    @property
    def mode(self) -> str:
        return "fake"

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        metrics = ExecutionMetrics(submit_started_at=time.perf_counter(), execution_started_at=time.perf_counter(), execution_finished_at=time.perf_counter(), total_ms=1)
        if request.role == "planner":
            return AgentExecutionResult(
                status="SUCCESS",
                structured_result={"version": "1.0", "summary": "fake", "tasks": [{"local_id": "coder", "role": "coder", "goal": request.goal, "dependencies": []}]},
                metrics=metrics,
            )
        if request.role == "coder":
            return AgentExecutionResult(status="SUCCESS", patch_ref={"task_local_id": "coder", "artifact_id": None, "patch_path": "/tmp/fake.patch", "sha256": "fake", "changed_files": ["app.py"]}, metrics=metrics)
        if request.role == "tester":
            return AgentExecutionResult(status="SUCCESS", structured_result={"returncode": 0, "passed": 1, "failed": 0, "failed_tests": [], "report_artifact_id": None}, metrics=metrics)
        if request.role == "reviewer":
            return AgentExecutionResult(status="SUCCESS", structured_result={"approved": True, "requirements_covered": ["fake"], "issues": [], "artifact_id": None}, metrics=metrics)
        return AgentExecutionResult(status="SUCCESS", structured_result={}, metrics=metrics)

    async def cancel_run(self, run_id: str) -> None:
        return None

    async def inject_fault(self, run_id: str, target: dict) -> dict:
        return {}

    async def get_execution_snapshot(self, run_id: str) -> dict:
        return {}


async def run_matrix(config: BenchmarkConfig, source_repo: str, fake: bool) -> list[RunMetric]:
    _ensure_git_safe_directory(source_repo)
    metrics: list[RunMetric] = []
    service = IncidentRunService()
    for mode in config.modes:
        for concurrency in config.concurrency_levels:
            total_runs = config.warmup_runs + config.measured_runs
            for index in range(total_runs):
                measured = index >= config.warmup_runs
                run_id = f"bench_{uuid4().hex}"
                started = time.perf_counter()
                run_config = IncidentRunConfig(
                    execution_mode=ExecutionMode.DIRECT if fake else ExecutionMode(mode),
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
                dependencies = {"provider": FakeBenchmarkProvider()} if fake else {}
                try:
                    result = await service.execute_run(run_config, "修复认证、JWT和订单安全问题", dependencies)
                    success = result["summary"]["status"] == "SUCCESS"
                    error = str(result["summary"].get("error") or "")
                except Exception as exc:
                    success = False
                    error = str(exc)
                metrics.append(
                    RunMetric(
                        benchmark_id=config.benchmark_id,
                        run_id=run_id,
                        mode=mode,
                        concurrency=concurrency,
                        measured=measured,
                        success=success,
                        total_ms=round((time.perf_counter() - started) * 1000, 3),
                        error=error,
                    )
                )
    return metrics


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
    parser.add_argument("--fake", action="store_true")
    args = parser.parse_args()
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
        prompt_hash="",
        graph_version="incident_repair_v1",
    )
    metrics = asyncio.run(run_matrix(config, args.source_repo, args.fake))
    write_benchmark_outputs(config, metrics)
    print(f"wrote run-data/benchmarks/{config.benchmark_id}")


if __name__ == "__main__":
    main()
