from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx
import yaml

from aruntime.api.client import AgentRuntimeClient
from applications.incident_repair.config import ExecutionMode, IncidentRunConfig
from applications.incident_repair.execution.base import AgentExecutionRequest, AgentExecutionResult, ExecutionMetrics, ExecutionProvider
from applications.incident_repair.services.run_service import IncidentRunService
from applications.incident_repair.services.run_service import register_demo_agents
from testing.perf.comparison.metrics import summarize_metrics
from testing.perf.comparison.paired_runner import check_pair_fairness
from testing.perf.comparison.schemas import BenchmarkConfig, PairedRun, RunMetric, TrialMetric, WorkflowMetric


TASK_DESCRIPTION = "修复认证、JWT和订单安全问题"
AGENTS_FILE = Path("examples/production_incident_demo/agents.yaml")
REQUIRED_AGENT_BACKENDS = {
    "architect": "native_planner",
    "coder_a": "codex_cli",
    "coder_b": "codex_cli",
    "tester": "direct_tool",
    "repair": "codex_cli",
    "reviewer": "codex_cli",
}


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
            pair_id=metric.pair_id,
            pair_index=metric.pair_index,
            latency_ms=metric.total_ms,
            success=metric.success,
            queue_wait_ms=metric.queue_wait_ms,
            backend_ms=metric.backend_ms,
            peak_rss_mb=metric.peak_rss_mb,
            error=metric.error,
            base_commit=metric.base_commit,
            prompt_hash=metric.prompt_hash,
            graph_version=metric.graph_version,
            deepseek_model=metric.deepseek_model,
            codex_model=metric.codex_model,
            codex_version=metric.codex_version,
            cpu_limit=metric.cpu_limit,
            memory_limit_mb=metric.memory_limit_mb,
            task_description_hash=metric.task_description_hash,
            experiment=metric.experiment,
            direct_retry_enabled=metric.direct_retry_enabled,
            runtime_fault_enabled=metric.runtime_fault_enabled,
            recovery_context_enabled=metric.recovery_context_enabled,
            fault_target_agent=metric.fault_target_agent,
            fault_trigger=metric.fault_trigger,
            fault_injected=metric.fault_injected,
            fault_injected_at_ms=metric.fault_injected_at_ms,
            fault_mode=metric.fault_mode,
            release_commit=metric.release_commit,
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
        "performance_claim_reason": config.performance_claim_reason,
        "prompt_hash": config.prompt_hash,
        "experiment": config.experiment,
        "direct_retry_enabled": config.direct_retry_enabled,
        "runtime_fault_enabled": config.runtime_fault_enabled,
        "recovery_context_enabled": config.recovery_context_enabled,
        "fault_target_agent": config.fault_target_agent,
        "fault_trigger": config.fault_trigger,
        "scenario_metadata": scenario_metadata(config),
        "registration": config.registration,
        "release_commit": config.release_commit,
        "all_pairs_comparable": all(pair.comparable for pair in pairs),
    }
    (out / "comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out


def build_measured_pairs(metrics: list[RunMetric]) -> list[PairedRun]:
    pairs: list[PairedRun] = []
    by_pair: dict[str, dict[str, RunMetric]] = {}
    for metric in metrics:
        if not metric.measured or not metric.pair_id:
            continue
        by_pair.setdefault(metric.pair_id, {})[metric.mode] = metric
    for pair_id, items in sorted(by_pair.items(), key=lambda item: (next(iter(item[1].values())).concurrency, next(iter(item[1].values())).pair_index, item[0])):
        direct = items.get("direct")
        runtime = items.get("runtime")
        if direct is None or runtime is None:
            sample = direct or runtime
            pairs.append(
                PairedRun(
                    pair_id=pair_id,
                    pair_index=sample.pair_index if sample else -1,
                    direct_run_id=direct.run_id if direct else "",
                    runtime_run_id=runtime.run_id if runtime else "",
                    comparable=False,
                    reason="missing:direct" if direct is None else "missing:runtime",
                )
            )
            continue
        pairs.append(check_pair_fairness(direct.model_dump(), runtime.model_dump()))
    return pairs


def scenario_metadata(config: BenchmarkConfig) -> dict:
    return {
        "experiment": config.experiment,
        "direct_retry_enabled": config.direct_retry_enabled,
        "runtime_fault_enabled": config.runtime_fault_enabled,
        "recovery_context_enabled": config.recovery_context_enabled,
        "fault_target_agent": config.fault_target_agent,
        "fault_trigger": config.fault_trigger,
    }


def prepare_runtime_benchmark_agents(config: BenchmarkConfig, base_url: str | None = None, agents_file: str | Path = AGENTS_FILE) -> dict:
    if "runtime" not in set(config.modes):
        return {"required": False, "registered": [], "agents": {}}
    base_url = base_url or os.environ.get("AGENTD_BASE_URL", "http://127.0.0.1:8234")
    client = AgentRuntimeClient(base_url)
    started = time.perf_counter()
    try:
        metrics = client.get_metrics()
    except Exception as exc:
        raise RuntimeError(f"runtime benchmark requires reachable agentd at {base_url}: {exc}") from exc
    runtime_config = metrics.get("runtime_config") if isinstance(metrics.get("runtime_config"), dict) else {}
    llm_backend = str(runtime_config.get("llm_backend") or "").strip()
    if llm_backend == "mock":
        raise RuntimeError("runtime benchmark requires agentd llm_backend != mock")
    if runtime_config and not runtime_config.get("llm_api_key_present"):
        raise RuntimeError("runtime benchmark requires LLM key inside agentd")
    registered = register_demo_agents(client, agents_file)
    agents_payload = client.list_agents()
    agents = agents_payload.get("agents") if isinstance(agents_payload, dict) else []
    agent_by_name = {str(item.get("name") or ""): item for item in agents if isinstance(item, dict)}
    yaml_agents = _load_agents_yaml(agents_file)
    missing = [name for name in REQUIRED_AGENT_BACKENDS if name not in agent_by_name]
    if missing:
        raise RuntimeError(f"runtime benchmark missing registered agents: {', '.join(missing)}")
    mismatches: list[str] = []
    for name, expected in REQUIRED_AGENT_BACKENDS.items():
        actual = str(((agent_by_name[name].get("backend") or {}).get("type") or ""))
        yaml_backend = str((((yaml_agents.get(name) or {}).get("backend") or {}).get("type") or ""))
        if actual != expected or yaml_backend != expected:
            mismatches.append(f"{name}:agentd={actual or 'missing'},yaml={yaml_backend or 'missing'},expected={expected}")
    reviewer_sandbox = str(((agent_by_name["reviewer"].get("backend") or {}).get("sandbox") or ""))
    if reviewer_sandbox and reviewer_sandbox != "read-only":
        mismatches.append(f"reviewer:sandbox={reviewer_sandbox},expected=read-only")
    if mismatches:
        raise RuntimeError("runtime benchmark agent backend mismatch: " + "; ".join(mismatches))
    return {
        "required": True,
        "base_url": base_url,
        "registered": registered,
        "registration_ms": round((time.perf_counter() - started) * 1000, 3),
        "llm_backend": llm_backend,
        "llm_api_key_present": bool(runtime_config.get("llm_api_key_present")),
        "agents": {name: {"backend": agent_by_name[name].get("backend"), "status": agent_by_name[name].get("status")} for name in REQUIRED_AGENT_BACKENDS},
    }


def _load_agents_yaml(agents_file: str | Path) -> dict[str, dict]:
    path = Path(agents_file)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    items = data.get("agents") if isinstance(data, dict) else []
    return {str(item.get("name")): item for item in items if isinstance(item, dict)}


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


async def run_one_workflow(
    service: IncidentRunService,
    config: BenchmarkConfig,
    source_repo: str,
    mode: str,
    concurrency: int,
    measured: bool,
    workflow_index: int,
    smoke: bool,
    trial_id: str,
    pair_id: str,
    pair_index: int,
) -> WorkflowMetric:
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
        fault_mode=config.runtime_fault_enabled if mode == "runtime" else config.direct_retry_enabled,
        fault_target_role=config.fault_target_agent,
        fault_trigger=config.fault_trigger,
        recovery_context_enabled=config.recovery_context_enabled,
    )
    dependencies = {"provider": SmokeBenchmarkProvider(), "integration_service": _SmokeIntegration()} if smoke else {}
    fault_task: asyncio.Task | None = None
    try:
        if not smoke and mode == "runtime" and config.runtime_fault_enabled:
            fault_task = asyncio.create_task(_inject_runtime_fault_on_event(run_id, config))
        result = await service.execute_run(run_config, TASK_DESCRIPTION, dependencies)
        fault_result = await fault_task if fault_task is not None else {}
        success = result["summary"]["status"] == "SUCCESS"
        error = str(result["summary"].get("error") or "")
        execution = result["summary"].get("execution") or {}
        resources = result["summary"].get("resources") or {}
    except Exception as exc:
        success = False
        error = str(exc)
        execution = {}
        resources = {}
        fault_result = {}
        if fault_task is not None:
            fault_task.cancel()
    return WorkflowMetric(
        trial_id=trial_id,
        workflow_index=workflow_index,
        benchmark_id=config.benchmark_id,
        run_id=run_id,
        mode=mode,
        concurrency=concurrency,
        measured=measured,
        pair_id=pair_id,
        pair_index=pair_index,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
        success=success,
        queue_wait_ms=float(execution.get("queue_wait_ms") or 0),
        backend_ms=float(execution.get("backend_ms") or 0),
        peak_rss_mb=float(resources.get("peak_rss_mb") or 0),
        error=error,
        base_commit=config.base_commit,
        prompt_hash=config.prompt_hash,
        graph_version=config.graph_version,
        deepseek_model=config.deepseek_model,
        codex_model=config.codex_model or "",
        codex_version=config.codex_version,
        cpu_limit=config.cpu_limit,
        memory_limit_mb=config.memory_limit_mb,
        task_description_hash=config.task_description_hash,
        experiment=config.experiment,
        direct_retry_enabled=config.direct_retry_enabled,
        runtime_fault_enabled=config.runtime_fault_enabled,
        recovery_context_enabled=config.recovery_context_enabled,
        fault_target_agent=config.fault_target_agent,
        fault_trigger=config.fault_trigger,
        fault_injected=bool(fault_result.get("injected")),
        fault_injected_at_ms=float(fault_result.get("injected_at_ms") or 0),
        fault_mode=run_config.fault_mode,
        release_commit=config.release_commit,
    )


async def run_trial(
    config: BenchmarkConfig,
    source_repo: str,
    mode: str,
    concurrency: int,
    measured: bool,
    smoke: bool,
    trial_index: int,
    pair_id: str | None = None,
    pair_index: int | None = None,
) -> tuple[list[WorkflowMetric], TrialMetric]:
    service = IncidentRunService()
    trial_id = f"{mode}_c{concurrency}_{trial_index}_{uuid4().hex[:8]}"
    pair_id = pair_id or f"c{concurrency}_{trial_index}"
    pair_index = trial_index if pair_index is None else pair_index
    started = time.perf_counter()
    runs = await asyncio.gather(
        *[
            run_one_workflow(
                service,
                config,
                source_repo,
                mode,
                concurrency,
                measured,
                index,
                smoke,
                trial_id,
                pair_id,
                pair_index,
            )
            for index in range(concurrency)
        ],
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
        pair_id=pair_id,
        pair_index=pair_index,
        batch_makespan_ms=makespan_ms,
        throughput_per_min=round((success_count / makespan_ms) * 60000, 6) if makespan_ms > 0 else 0,
        success_count=success_count,
        failure_count=len(runs) - success_count,
        peak_rss_mb=max([run.peak_rss_mb for run in runs] or [0]),
        experiment=config.experiment,
        direct_retry_enabled=config.direct_retry_enabled,
        runtime_fault_enabled=config.runtime_fault_enabled,
        recovery_context_enabled=config.recovery_context_enabled,
        fault_target_agent=config.fault_target_agent,
        fault_trigger=config.fault_trigger,
    )
    return runs, trial


async def _inject_runtime_fault_on_event(run_id: str, config: BenchmarkConfig) -> dict:
    base_url = os.environ.get("AGENTD_BASE_URL", "http://127.0.0.1:8234")
    client = AgentRuntimeClient(base_url)
    deadline = time.time() + 900
    last_id = 0
    workflow_started = time.perf_counter()
    while time.time() < deadline:
        events = _run_events(base_url, run_id, last_id)
        for event in events:
            try:
                last_id = max(last_id, int(event.get("id") or event.get("event_id") or last_id))
            except (TypeError, ValueError):
                pass
            if _matches_fault_trigger(base_url, event, config):
                injected_at_ms = round((time.perf_counter() - workflow_started) * 1000, 3)
                result = client.inject_worker_sigkill(config.fault_target_agent)
                return {
                    "injected": True,
                    "injected_at_ms": injected_at_ms,
                    "event_id": event.get("id") or event.get("event_id"),
                    "event_name": _event_name(event),
                    "target_agent": config.fault_target_agent,
                    "result": result,
                }
        summary = _run_summary(base_url, run_id)
        if summary.get("status") in {"SUCCESS", "FAILED", "TIMEOUT", "CANCELLED"}:
            return {"injected": False, "reason": "workflow finished before fault trigger"}
        await asyncio.sleep(0.25)
    return {"injected": False, "reason": f"fault trigger timeout: {config.fault_trigger}"}


def _matches_fault_trigger(base_url: str, event: dict, config: BenchmarkConfig) -> bool:
    configured = config.fault_trigger.replace("_", ".")
    names = {configured}
    if configured == "backend.started":
        names.add("backend_started")
    if _event_name(event) not in names:
        return False
    return _event_agent_name(base_url, event) == config.fault_target_agent


def _run_events(base_url: str, run_id: str, after_id: int = 0) -> list[dict]:
    try:
        data = httpx.get(f"{base_url}/runs/{run_id}/events", params={"after_id": after_id}, timeout=3, trust_env=False).json()
    except Exception:
        return []
    events = data.get("events")
    return events if isinstance(events, list) else []


def _run_summary(base_url: str, run_id: str) -> dict:
    try:
        data = httpx.get(f"{base_url}/runs/{run_id}/summary", timeout=3, trust_env=False).json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _task(base_url: str, task_id: str) -> dict:
    try:
        data = httpx.get(f"{base_url}/tasks/{task_id}", timeout=3, trust_env=False).json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _event_name(event: dict) -> str:
    return str(event.get("name") or "")


def _event_detail(event: dict) -> dict:
    raw = event.get("data")
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
    elif isinstance(raw, dict):
        payload = raw
    else:
        payload = {}
    detail = event.get("detail")
    if isinstance(detail, dict):
        payload.update(detail)
    return payload


def _event_agent_name(base_url: str, event: dict) -> str:
    detail = _event_detail(event)
    if detail.get("agent_name"):
        return str(detail["agent_name"])
    task_id = str(event.get("task_id") or detail.get("task_id") or "")
    attempt_id = str(detail.get("attempt_id") or "")
    if not task_id:
        return ""
    task = _task(base_url, task_id)
    for attempt in task.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        if attempt_id and attempt.get("attempt_id") != attempt_id:
            continue
        if attempt.get("agent_name"):
            return str(attempt["agent_name"])
    return ""


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
            pair_id=item.pair_id,
            pair_index=item.pair_index,
            success=item.success,
            total_ms=item.latency_ms,
            queue_wait_ms=item.queue_wait_ms,
            backend_ms=item.backend_ms,
            peak_rss_mb=item.peak_rss_mb,
            error=item.error,
            base_commit=item.base_commit,
            prompt_hash=item.prompt_hash,
            graph_version=item.graph_version,
            deepseek_model=item.deepseek_model,
            codex_model=item.codex_model,
            codex_version=item.codex_version,
            cpu_limit=item.cpu_limit,
            memory_limit_mb=item.memory_limit_mb,
            task_description_hash=item.task_description_hash,
            experiment=item.experiment,
            direct_retry_enabled=item.direct_retry_enabled,
            runtime_fault_enabled=item.runtime_fault_enabled,
            recovery_context_enabled=item.recovery_context_enabled,
            fault_target_agent=item.fault_target_agent,
            fault_trigger=item.fault_trigger,
            fault_injected=item.fault_injected,
            fault_injected_at_ms=item.fault_injected_at_ms,
            fault_mode=item.fault_mode,
            release_commit=item.release_commit,
        )
        for item in workflow_metrics
    ]


async def run_matrix_detailed(config: BenchmarkConfig, source_repo: str, smoke: bool = False) -> tuple[list[WorkflowMetric], list[TrialMetric]]:
    _ensure_git_safe_directory(source_repo)
    if not smoke and "runtime" in set(config.modes) and not config.registration:
        config.registration = prepare_runtime_benchmark_agents(config)
    workflow_metrics: list[WorkflowMetric] = []
    trial_metrics: list[TrialMetric] = []
    modes = list(config.modes)
    for concurrency in config.concurrency_levels:
        total_runs = config.warmup_runs + config.measured_runs
        for index in range(total_runs):
            measured = index >= config.warmup_runs
            order = modes
            if set(modes) == {"direct", "runtime"} and len(modes) == 2:
                order = ["direct", "runtime"] if index % 2 == 0 else ["runtime", "direct"]
            pair_id = f"c{concurrency}_{index}"
            for mode in order:
                workflows, trial = await run_trial(config, source_repo, mode, concurrency, measured, smoke, index, pair_id=pair_id, pair_index=index)
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


def require_clean_source_tree(repo: str | Path = ".") -> str:
    repo = Path(repo).resolve()
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(
        ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
        text=True,
    ).strip()
    if status:
        raise RuntimeError("formal benchmark requires a clean tracked working tree")
    return head


def normalize_experiment(value: str) -> str:
    normalized = value.strip().replace("-", "_")
    allowed = {"baseline", "fault_recovery", "recovery_context"}
    if normalized not in allowed:
        raise ValueError(f"unsupported experiment: {value}")
    return normalized


def parse_recovery_context(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "on":
        return True
    if normalized == "off":
        return False
    raise ValueError("--recovery-context must be on or off")


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
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--experiment", default="baseline", choices=["baseline", "fault-recovery", "fault_recovery", "recovery-context", "recovery_context"])
    parser.add_argument("--direct-retry", action="store_true")
    parser.add_argument("--runtime-fault", action="store_true")
    parser.add_argument("--recovery-context", default="on", choices=["on", "off"])
    parser.add_argument("--fault-target-agent", default="coder_a")
    parser.add_argument("--fault-trigger", default="backend.started")
    parser.add_argument("--output-root", default="run-data/benchmarks")
    args = parser.parse_args()
    smoke = bool(args.smoke or args.fake)
    experiment = normalize_experiment(args.experiment)
    recovery_context_enabled = parse_recovery_context(args.recovery_context)
    performance_claim_allowed = not smoke
    performance_claim_reason = ""
    release_commit = ""
    if smoke:
        performance_claim_reason = "smoke run"
    elif args.allow_dirty:
        performance_claim_allowed = False
        performance_claim_reason = "allow-dirty"
        release_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    else:
        release_commit = require_clean_source_tree()
    config = BenchmarkConfig(
        benchmark_id=f"{args.task_case}_comparison",
        task_case=args.task_case,
        modes=args.modes.split(","),
        concurrency_levels=[int(item) for item in args.concurrency.split(",")],
        warmup_runs=args.warmup,
        measured_runs=args.runs,
        cpu_limit=args.cpu_limit,
        memory_limit_mb=args.memory_limit_mb,
        experiment=experiment,  # type: ignore[arg-type]
        direct_retry_enabled=bool(args.direct_retry),
        runtime_fault_enabled=bool(args.runtime_fault),
        recovery_context_enabled=recovery_context_enabled,
        fault_target_agent=args.fault_target_agent,
        fault_trigger=args.fault_trigger,
        deepseek_model="deepseek-v4-flash",
        base_commit=args.base_commit,
        prompt_hash=compute_prompt_hash(),
        graph_version="incident_repair_v1",
        release_commit=release_commit,
        codex_version=_optional_stdout(["codex", "--version"]),
        task_description_hash=hashlib.sha256(TASK_DESCRIPTION.encode("utf-8")).hexdigest(),
        data_kind="synthetic_smoke" if smoke else "real_agent",
        performance_claim_allowed=performance_claim_allowed,
        performance_claim_reason=performance_claim_reason,
    )
    workflows, trials = asyncio.run(run_matrix_detailed(config, args.source_repo, smoke))
    metrics = [
        RunMetric(
            benchmark_id=item.benchmark_id,
            run_id=item.run_id,
            mode=item.mode,
            concurrency=item.concurrency,
            measured=item.measured,
            pair_id=item.pair_id,
            pair_index=item.pair_index,
            success=item.success,
            total_ms=item.latency_ms,
            queue_wait_ms=item.queue_wait_ms,
            backend_ms=item.backend_ms,
            peak_rss_mb=item.peak_rss_mb,
            error=item.error,
            base_commit=item.base_commit,
            prompt_hash=item.prompt_hash,
            graph_version=item.graph_version,
            deepseek_model=item.deepseek_model,
            codex_model=item.codex_model,
            codex_version=item.codex_version,
            cpu_limit=item.cpu_limit,
            memory_limit_mb=item.memory_limit_mb,
            task_description_hash=item.task_description_hash,
            experiment=item.experiment,
            direct_retry_enabled=item.direct_retry_enabled,
            runtime_fault_enabled=item.runtime_fault_enabled,
            recovery_context_enabled=item.recovery_context_enabled,
            fault_target_agent=item.fault_target_agent,
            fault_trigger=item.fault_trigger,
            fault_injected=item.fault_injected,
            fault_injected_at_ms=item.fault_injected_at_ms,
            fault_mode=item.fault_mode,
            release_commit=item.release_commit,
        )
        for item in workflows
    ]
    out = write_benchmark_outputs(config, metrics, root=args.output_root, workflow_metrics=workflows, trial_metrics=trials)
    print(f"wrote {out}")


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


def _optional_stdout(args: list[str], cwd: str | Path = ".", timeout: int = 10) -> str:
    try:
        proc = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=False, timeout=timeout)
    except Exception:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


if __name__ == "__main__":
    main()
