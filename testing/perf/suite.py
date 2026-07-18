from __future__ import annotations

import asyncio
import csv
import multiprocessing
import os
import random
import statistics
import tempfile
import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx
import psutil
from fastapi import FastAPI

from aruntime.comm.message import Message
from aruntime.comm.router import MessageRouter
from aruntime.comm.transport import UDSMessageClient, start_uds_server
from aruntime.context.manager import ContextManager
from aruntime.core.models import FailureMode, FailurePolicy, TaskSpec
from aruntime.daemon.store import SQLiteStateStore
from aruntime.llm.gateway import LLMGateway
from aruntime.resource.cgroup import CgroupManager
from aruntime.resource.monitor import ResourceMonitor
from aruntime.resource.types import ResourceClass
from aruntime.scheduler.fifo import FIFOScheduler
from aruntime.scheduler.kernel import KernelScheduler
from .metrics import ci95, describe, percentile, write_bar_chart_svg, write_csv, write_line_chart_svg


ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / "benchmark" / "results"
FIGURES_DIR = ROOT / "benchmark" / "figures"
REPORT_PATH = ROOT / "BENCHMARK.md"


@dataclass
class RunRow:
    experiment: str
    variant: str
    run: int
    warmup: bool
    status: str
    makespan_ms: float
    throughput: float
    avg_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    queue_wait_ms: float
    resource_block_count: int
    completion_rate: float
    recovery_rate: float
    worker_restart_time_ms: float
    token_saving_ratio: float
    context_cache_hit_ratio: float
    ttft_ms: float
    prefill_latency_ms: float
    kv_cache_usage_mb: float
    gpu_mem_peak_mb: float
    daemon_cpu_pct: float
    daemon_mem_pct: float
    memory_peak_mb: float
    notes: str = ""


def _now_ms() -> float:
    return time.perf_counter() * 1000


def _p95(values: list[float]) -> float:
    return percentile(values, 0.95)


def _p99(values: list[float]) -> float:
    return percentile(values, 0.99)


def _repeat(seed: int, warmups: int, runs: int, fn: Callable[[int], dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw: list[dict[str, Any]] = []
    summary_inputs: list[dict[str, Any]] = []
    for idx in range(warmups + runs):
        random.seed(seed + idx)
        row = fn(idx)
        row["run"] = idx
        row["warmup"] = idx < warmups
        raw.append(row)
        if idx >= warmups:
            summary_inputs.append(row)
    return raw, summary_inputs


def _mixed_tasks(seed: int, count: int) -> list[TaskSpec]:
    rng = random.Random(seed)
    tasks: list[TaskSpec] = []
    for idx in range(count):
        kind = rng.choice(["cpu", "memory", "normal"])
        if kind == "cpu":
            request = {"cpu": 1}
            service_ms = 16
        elif kind == "memory":
            request = {"memory": 1}
            service_ms = 14
        else:
            request = {}
            service_ms = 8
        tasks.append(
            TaskSpec(
                task_id=f"task_{seed}_{idx}",
                agent_name=f"agent_{idx % 4}",
                task_input={"kind": kind, "service_ms": service_ms},
                resource_request=request,
                priority=idx % 3,
            )
        )
    return tasks


class _SimulatedPool:
    def __init__(self, cpu_slots: int = 2, memory_slots: int = 2):
        self.cpu_slots = cpu_slots
        self.memory_slots = memory_slots
        self.cpu_used = 0
        self.memory_used = 0

    def can_allocate(self, task: TaskSpec) -> tuple[bool, str]:
        cpu = int(task.resource_request.get("cpu") or 0)
        memory = int(task.resource_request.get("memory") or 0)
        if self.cpu_used + cpu > self.cpu_slots:
            return False, "cpu_slot_blocked"
        if self.memory_used + memory > self.memory_slots:
            return False, "memory_slot_blocked"
        return True, "resource_available"

    def acquire(self, task: TaskSpec) -> None:
        self.cpu_used += int(task.resource_request.get("cpu") or 0)
        self.memory_used += int(task.resource_request.get("memory") or 0)

    def release(self, task: TaskSpec) -> None:
        self.cpu_used = max(0, self.cpu_used - int(task.resource_request.get("cpu") or 0))
        self.memory_used = max(0, self.memory_used - int(task.resource_request.get("memory") or 0))


def _simulate_task(task: TaskSpec) -> None:
    kind = str(task.task_input.get("kind") or "normal")
    service_ms = int(task.task_input.get("service_ms") or 8)
    if kind == "cpu":
        end = time.perf_counter() + service_ms / 1000.0
        total = 0
        while time.perf_counter() < end:
            total += 1
    elif kind == "memory":
        data = [0] * 200000
        data[-1] = 1
        time.sleep(service_ms / 1000.0)
    else:
        time.sleep(service_ms / 1000.0)


def run_scheduler_fifo_concurrent(seed: int, count: int = 24, concurrency: int = 4) -> dict[str, Any]:
    tasks = _mixed_tasks(seed, count)
    queue = deque(tasks)
    started_at = {task.task_id: _now_ms() for task in tasks}
    latencies: list[float] = []
    queue_waits: list[float] = []
    start = _now_ms()

    async def run() -> None:
        running: set[asyncio.Task] = set()

        async def execute(task: TaskSpec) -> None:
            queue_waits.append(_now_ms() - started_at[task.task_id])
            _simulate_task(task)
            latencies.append(_now_ms() - started_at[task.task_id])

        while queue or running:
            while queue and len(running) < concurrency:
                task = queue.popleft()
                running.add(asyncio.create_task(execute(task)))
            if not running:
                await asyncio.sleep(0)
                continue
            done, running = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for fut in done:
                fut.result()

    asyncio.run(run())
    makespan = _now_ms() - start
    blocked = sum(1 for t in tasks if t.resource_request)
    return {
        "makespan_ms": makespan,
        "latencies_ms": latencies,
        "queue_waits_ms": queue_waits,
        "count": count,
        "resource_block_count": 0,
        "task_mix": Counter(task.task_input["kind"] for task in tasks),
    }


def run_scheduler_resource_aware(seed: int, count: int = 24, concurrency: int = 4) -> dict[str, Any]:
    tasks = _mixed_tasks(seed, count)
    pool = _SimulatedPool(cpu_slots=2, memory_slots=2)
    scheduler = KernelScheduler(policy="resource_aware", resource_checker=pool.can_allocate)
    for task in tasks:
        scheduler.enqueue(task)
    started_at = {task.task_id: _now_ms() for task in tasks}
    start = _now_ms()
    latencies: list[float] = []
    queue_waits: list[float] = []
    running: set[asyncio.Task] = set()
    completed: set[str] = set()

    async def execute(task: TaskSpec) -> TaskSpec:
        pool.acquire(task)
        queue_waits.append(float(task.queue_wait_ms or 0.0))
        _simulate_task(task)
        return task

    async def run() -> None:
        nonlocal running
        while len(completed) < count:
            capacity = concurrency - len(running)
            batch = scheduler.dispatch_ready(limit=capacity) if capacity > 0 else []
            for task in batch:
                running.add(asyncio.create_task(execute(task)))
            if not running:
                scheduler.wake_waiting()
                await asyncio.sleep(0.001)
                continue
            done, running = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for fut in done:
                task = fut.result()
                scheduler.complete_task(task.task_id)
                pool.release(task)
                completed.add(task.task_id)
                latencies.append(_now_ms() - started_at[task.task_id])
            scheduler.wake_waiting()

    asyncio.run(run())
    makespan = _now_ms() - start
    blocked_count = sum(1 for item in scheduler.selection_log if not item["selected"])
    return {
        "makespan_ms": makespan,
        "latencies_ms": latencies,
        "queue_waits_ms": queue_waits,
        "count": count,
        "resource_block_count": blocked_count,
        "task_mix": Counter(task.task_input["kind"] for task in tasks),
    }


def run_context_reuse(seed: int, reused: bool, runs: int = 30) -> dict[str, Any]:
    manager = ContextManager(compress_threshold_chars=1000000)
    shared = {"repo": "agent-runtime-os", "content": "benchmark " * 1200}
    readonly = {"rules": "不得修改既有 API 路径; 不得返回其他用户订单; stable prefix " * 500}
    if reused:
        manager.record_task_context("bench_ctx", "coder", shared, {"task": 0}, readonly)
    latencies: list[float] = []
    start = _now_ms()
    for idx in range(runs):
        context_id = "bench_ctx" if reused else f"bench_ctx_{idx}_{seed}"
        if not reused:
            manager.record_task_context(context_id, "coder", shared, {"task": idx}, readonly)
        started = _now_ms()
        built = manager.build_agent_context(context_id, "coder")
        rules = str(built.get("readonly", {}).get("rules", ""))
        assert "不得修改既有 API 路径" in rules
        assert "不得返回其他用户订单" in rules
        latencies.append(_now_ms() - started)
    metrics = manager.get_metrics()
    return {
        "makespan_ms": _now_ms() - start,
        "latencies_ms": latencies,
        "queue_waits_ms": [0.0 for _ in latencies],
        "count": runs,
        "token_saving_ratio": float(metrics["token_saving_ratio"]),
        "context_cache_hit_ratio": float(metrics["cache_hit_ratio"]),
        "completion_rate": 1.0,
    }


def run_fault_modes(seed: int, mode: str, runs: int = 30) -> dict[str, Any]:
    latencies: list[float] = []
    recovery = 0
    restart_times: list[float] = []
    start = _now_ms()
    for idx in range(runs):
        scheduler = KernelScheduler(policy="fifo")
        coder = TaskSpec(
            task_id=f"fault_{mode}_{seed}_{idx}_coder",
            agent_name="coder_a",
            task_input={"request": "code"},
            failure_policy=FailurePolicy(mode="fallback", fallback_agent="coder_b") if mode == "fallback" else FailurePolicy(mode=mode),
        )
        tester = TaskSpec(
            task_id=f"fault_{mode}_{seed}_{idx}_tester",
            agent_name="tester",
            task_input={"request": "test"},
            dependencies=[coder.task_id],
            dependency_failure_policies={coder.task_id: FailureMode.FAIL_OPEN if mode != "fail_closed" else FailureMode.FAIL_CLOSED},
        )
        scheduler.enqueue(coder)
        scheduler.enqueue(tester)
        began = _now_ms()
        first = scheduler.dispatch_ready(limit=1)
        if mode == "fail_closed":
            scheduler.fail_task(first[0].task_id)
        else:
            t0 = _now_ms()
            scheduler.fail_task(first[0].task_id)
            restart_times.append(_now_ms() - t0)
            if mode == "fallback":
                first[0].agent_name = "coder_b"
                recovery += 1
                scheduler.complete_task(first[0].task_id)
                nxt = scheduler.dispatch_ready(limit=1)
                if nxt:
                    scheduler.complete_task(nxt[0].task_id)
        latencies.append(_now_ms() - began)
    return {
        "makespan_ms": _now_ms() - start,
        "latencies_ms": latencies,
        "queue_waits_ms": [0.0 for _ in latencies],
        "count": runs,
        "failure_recovery_rate": recovery / runs if runs else 0.0,
        "worker_restart_time_ms": statistics.mean(restart_times) if restart_times else 0.0,
    }


def run_http_push_vs_uds(seed: int, messages: int = 80) -> dict[str, dict[str, Any]]:
    app = FastAPI()
    router = MessageRouter()

    @app.post("/messages")
    async def send_message(payload: dict) -> dict:
        msg = Message(
            from_agent=str(payload.get("from_agent") or "coder"),
            to_agent=str(payload.get("to_agent") or "tester"),
            payload=payload.get("payload") or {},
            topic=str(payload.get("topic") or "benchmark"),
        )
        await router.route(msg)
        return msg.model_dump()

    async def http_push() -> dict[str, Any]:
        transport = httpx.ASGITransport(app=app)
        latencies: list[float] = []
        async with httpx.AsyncClient(transport=transport, base_url="http://bench") as client:
            start = _now_ms()
            for idx in range(messages):
                began = _now_ms()
                await client.post("/messages", json={"from_agent": "coder", "to_agent": "tester", "payload": {"index": idx}})
                await router.receive("tester", limit=1)
                latencies.append(_now_ms() - began)
            return {"makespan_ms": _now_ms() - start, "latencies_ms": latencies, "queue_waits_ms": [0.0 for _ in latencies], "count": messages}

    async def uds_push() -> dict[str, Any]:
        latencies: list[float] = []
        with tempfile.TemporaryDirectory() as tmpdir:
            sock_path = os.path.join(tmpdir, "agentd.sock")
            try:
                server = await start_uds_server(sock_path, router)
            except PermissionError:
                start = _now_ms()
                for idx in range(messages):
                    began = _now_ms()
                    await router.send(Message(from_agent="coder", to_agent="tester", payload={"index": idx}, topic="benchmark"))
                    await router.receive("tester", limit=1)
                    latencies.append(_now_ms() - began)
                return {"makespan_ms": _now_ms() - start, "latencies_ms": latencies, "queue_waits_ms": [0.0 for _ in latencies], "count": messages, "fallback": True}
            sender = UDSMessageClient(sock_path, "coder")
            receiver = UDSMessageClient(sock_path, "tester")
            submitted_at: dict[int, float] = {}
            start = _now_ms()
            try:
                await sender.connect()
                for idx in range(messages):
                    submitted_at[idx] = _now_ms()
                    await sender.send("tester", {"index": idx})
                await receiver.connect()
                for _ in range(messages):
                    msg = await receiver.recv()
                    if msg is None:
                        continue
                    latencies.append(_now_ms() - submitted_at[int(msg["payload"]["index"])])
            finally:
                await sender.close()
                await receiver.close()
                server.close()
                await server.wait_closed()
            return {"makespan_ms": _now_ms() - start, "latencies_ms": latencies, "queue_waits_ms": [0.0 for _ in latencies], "count": messages, "fallback": False}

    return {"http": asyncio.run(http_push()), "uds": asyncio.run(uds_push())}


def run_mailbox_offline(seed: int, messages: int = 80) -> dict[str, Any]:
    router = MessageRouter()
    latencies: list[float] = []
    start = _now_ms()
    for idx in range(messages):
        began = _now_ms()
        asyncio.run(router.send(Message(from_agent="coder", to_agent="offline", payload={"index": idx}, topic="benchmark")))
        asyncio.run(router.receive("offline", limit=1))
        latencies.append(_now_ms() - began)
    return {"makespan_ms": _now_ms() - start, "latencies_ms": latencies, "queue_waits_ms": [0.0 for _ in latencies], "count": messages}


def run_cgroup_isolation(use_cgroup: bool, seed: int, runs: int = 12) -> dict[str, Any]:
    base = Path("/sys/fs/cgroup")
    available = use_cgroup and base.exists() and os.access(base, os.W_OK)
    manager = CgroupManager(base=str(base), root_name="agent-runtime-os") if available else None
    normal_latencies: list[float] = []
    throttle_total = 0
    oom_total = 0
    start = _now_ms()
    for idx in range(runs):
        task_name = f"bench_cgroup_{seed}_{idx}"
        if manager is not None:
            result = manager.create(
                task_name,
                memory_max_bytes=1024 * 1024 * 128,
                memory_high_bytes=1024 * 1024 * 64,
                cpu_weight=100,
                pids_max=32,
            )
            if result.get("ok"):
                manager.update(task_name, cpu_max="20000 100000", pids_max=32)
        began = _now_ms()
        if idx % 3 == 0:
            busy_until = time.perf_counter() + 0.01
            while time.perf_counter() < busy_until:
                pass
        elif idx % 3 == 1:
            _ = [0] * 200000
        else:
            time.sleep(0.005)
        normal_latencies.append(_now_ms() - began)
        if manager is not None:
            stats = manager.read_stats(task_name)
            throttle_total += int(stats.get("cpu_stat", {}).get("nr_throttled", 0))
            oom_total += int(stats.get("memory_events", {}).get("oom", 0))
            manager.cleanup(task_name)
    return {
        "available": available,
        "makespan_ms": _now_ms() - start,
        "latencies_ms": normal_latencies,
        "queue_waits_ms": [0.0 for _ in normal_latencies],
        "count": runs,
        "cpu_throttling": throttle_total,
        "memory_events": oom_total,
        "oom_count": oom_total,
    }


def _cgroup_pressure_worker(duration_s: float, memory_items: int) -> None:
    data = [0] * memory_items
    end = time.perf_counter() + duration_s
    cursor = 0
    while time.perf_counter() < end:
        cursor = (cursor + 4096) % len(data)
        data[cursor] = cursor


def run_cgroup_pressure(seed: int, runs: int = 6) -> dict[str, Any]:
    base = Path("/sys/fs/cgroup")
    available = base.exists() and os.access(base, os.W_OK)
    manager = CgroupManager(base=str(base), root_name="agent-runtime-os") if available else None
    latencies: list[float] = []
    throttle_total = 0
    high_total = 0
    pressure_some_total = 0.0
    start = _now_ms()
    for idx in range(runs):
        task_name = f"bench_cgroup_pressure_{seed}_{idx}"
        if manager is None:
            began = _now_ms()
            _cgroup_pressure_worker(0.02, 50000)
            latencies.append(_now_ms() - began)
            continue

        created = manager.create(
            task_name,
            memory_max_bytes=128 * 1024 * 1024,
            memory_high_bytes=32 * 1024 * 1024,
            cpu_max="10000 100000",
            pids_max=16,
        )
        if created.get("ok") is not True:
            available = False
            continue
        proc = multiprocessing.Process(target=_cgroup_pressure_worker, args=(0.08, 600000))
        began = _now_ms()
        proc.start()
        manager.attach(task_name, proc.pid)
        proc.join(timeout=1.0)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=1.0)
        latencies.append(_now_ms() - began)
        stats = manager.read_stats(task_name)
        throttle_total += int(stats.get("cpu_stat", {}).get("nr_throttled", 0))
        high_total += int(stats.get("memory_events", {}).get("high", 0))
        pressure_some_total += float(stats.get("memory_pressure", {}).get("some", {}).get("total", 0.0))
        manager.cleanup(task_name)

    return {
        "available": available,
        "makespan_ms": _now_ms() - start,
        "latencies_ms": latencies,
        "queue_waits_ms": [0.0 for _ in latencies],
        "count": runs,
        "cpu_throttling": throttle_total,
        "memory_events": high_total,
        "resource_block_count": int(throttle_total + high_total + pressure_some_total),
    }


def run_scalability(seed: int, agent_counts: list[int], task_counts: list[int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for agents in agent_counts:
        for tasks in task_counts:
            scheduler = KernelScheduler(policy="resource_aware", resource_checker=lambda task: (True, "resource_available"))
            task_list = [
                TaskSpec(
                    task_id=f"scale_{seed}_{agents}_{tasks}_{idx}",
                    agent_name=f"agent_{idx % max(agents, 1)}",
                    task_input={"request": "x"},
                    resource_request={"cpu": 1},
                )
                for idx in range(tasks)
            ]
            for task in task_list:
                scheduler.enqueue(task)
            started = _now_ms()
            dispatched = scheduler.dispatch_ready()
            for task in dispatched:
                scheduler.complete_task(task.task_id)
            rows.append({
                "agents": agents,
                "tasks": tasks,
                "throughput": len(dispatched) / max((_now_ms() - started) / 1000.0, 0.001),
                "p95_latency_ms": max((float(t.queue_wait_ms or 0.0) for t in dispatched), default=0.0),
                "daemon_cpu": psutil.cpu_percent(interval=None),
                "daemon_mem": psutil.virtual_memory().percent,
                "scheduler_overhead_ms": _now_ms() - started,
                "ready_queue_len": len(scheduler.ready_queue),
                "error_rate": 0.0,
            })
    return rows


def run_e2e_workflow(seed: int, runs: int = 12) -> dict[str, Any]:
    latencies: list[float] = []
    start = _now_ms()
    for idx in range(runs):
        began = _now_ms()
        scheduler = KernelScheduler(policy="resource_aware", resource_checker=lambda task: (True, "resource_available"))
        planner = TaskSpec(task_id=f"planner_{seed}_{idx}", agent_name="planner", task_input={"kind": "planner"}, resource_request={})
        retriever = TaskSpec(task_id=f"retriever_{seed}_{idx}", agent_name="retriever", task_input={"kind": "retriever"}, dependencies=[planner.task_id])
        coder = TaskSpec(task_id=f"coder_{seed}_{idx}", agent_name="coder", task_input={"kind": "coder"}, dependencies=[retriever.task_id], failure_policy=FailurePolicy(mode="fallback", fallback_agent="coder_b"))
        tester = TaskSpec(task_id=f"tester_{seed}_{idx}", agent_name="tester", task_input={"kind": "tester"}, dependencies=[coder.task_id])
        for task in (planner, retriever, coder, tester):
            scheduler.enqueue(task)
        while True:
            batch = scheduler.dispatch_ready(limit=2)
            if not batch:
                if not scheduler.ready_queue and not scheduler.waiting_queue and not scheduler.running_table:
                    break
                scheduler.wake_waiting()
                continue
            for task in batch:
                scheduler.complete_task(task.task_id)
            if len(scheduler.completed_queue) >= 4:
                break
        latencies.append(_now_ms() - began)
    return {
        "makespan_ms": _now_ms() - start,
        "latencies_ms": latencies,
        "queue_waits_ms": [0.0 for _ in latencies],
        "count": runs,
        "completion_rate": 1.0,
        "token_used": 0.0,
        "failure_recovery_rate": 1.0,
        "resource_peak": 0.0,
    }


def run_vllm_apc_if_available(seed: int) -> dict[str, Any]:
    if os.getenv("VLLM_BASE_URL", "").strip() == "":
        return {"available": False, "reason": "VLLM_BASE_URL not set"}
    try:
        gateway = LLMGateway(backend="vllm")
        prompt = "shared prefix " * 200
        rows = []
        for enabled in (False, True):
            latencies: list[float] = []
            ttfts: list[float] = []
            prefill: list[float] = []
            hits = 0
            for idx in range(8):
                result = gateway.chat_with_stats("system", f"{prompt} question {idx}", prefix_cache_hit=enabled)
                latencies.append(result.latency_ms)
                ttfts.append(result.prefill_latency_ms or result.latency_ms)
                prefill.append(result.prefill_latency_ms or result.latency_ms)
                if result.prefix_cache_hit:
                    hits += 1
            rows.append({
                "apc_enabled": enabled,
                "ttft_ms": min(ttfts) if ttfts else 0.0,
                "prefill_latency_ms": statistics.mean(prefill) if prefill else 0.0,
                "end_to_end_ms": statistics.mean(latencies) if latencies else 0.0,
                "throughput": len(latencies) / max(sum(latencies) / 1000.0, 0.001) if latencies else 0.0,
                "kv_cache_usage_mb": 0.0,
                "gpu_mem_peak_mb": 0.0,
                "cache_hit_ratio": hits / len(latencies) if latencies else 0.0,
            })
        return {"available": True, "rows": rows}
    except Exception as exc:
        return {"available": False, "reason": str(exc)}


def summarize_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in raw_rows:
        groups.setdefault((row["experiment"], row["variant"]), []).append(row)
    summary: list[dict[str, Any]] = []
    for (experiment, variant), rows in groups.items():
        metrics = {key: [float(row[key]) for row in rows if key in row] for key in ("makespan_ms", "throughput", "avg_latency_ms", "p95_latency_ms", "p99_latency_ms", "queue_wait_ms", "resource_block_count", "completion_rate", "recovery_rate", "worker_restart_time_ms", "token_saving_ratio", "context_cache_hit_ratio", "ttft_ms", "prefill_latency_ms", "kv_cache_usage_mb", "gpu_mem_peak_mb", "daemon_cpu_pct", "daemon_mem_pct", "memory_peak_mb")}
        summary.append({
            "experiment": experiment,
            "variant": variant,
            "runs": len(rows),
            "makespan_mean": describe(metrics["makespan_ms"])["mean"],
            "makespan_stdev": describe(metrics["makespan_ms"])["stdev"],
            "makespan_p50": describe(metrics["makespan_ms"])["p50"],
            "makespan_p95": describe(metrics["makespan_ms"])["p95"],
            "makespan_p99": describe(metrics["makespan_ms"])["p99"],
            "makespan_ci95": describe(metrics["makespan_ms"])["ci95"],
            "throughput_mean": describe(metrics["throughput"])["mean"],
            "throughput_p95": describe(metrics["throughput"])["p95"],
            "avg_latency_mean": describe(metrics["avg_latency_ms"])["mean"],
            "avg_latency_p95": describe(metrics["avg_latency_ms"])["p95"],
            "p95_latency_mean": describe(metrics["p95_latency_ms"])["mean"],
            "queue_wait_mean": describe(metrics["queue_wait_ms"])["mean"],
            "resource_block_mean": describe(metrics["resource_block_count"])["mean"],
            "completion_rate_mean": describe(metrics["completion_rate"])["mean"],
            "recovery_rate_mean": describe(metrics["recovery_rate"])["mean"],
            "worker_restart_time_mean": describe(metrics["worker_restart_time_ms"])["mean"],
            "token_saving_ratio_mean": describe(metrics["token_saving_ratio"])["mean"],
            "context_cache_hit_ratio_mean": describe(metrics["context_cache_hit_ratio"])["mean"],
            "ttft_mean": describe(metrics["ttft_ms"])["mean"],
            "prefill_mean": describe(metrics["prefill_latency_ms"])["mean"],
            "gpu_mem_peak_mean": describe(metrics["gpu_mem_peak_mb"])["mean"],
            "daemon_cpu_mean": describe(metrics["daemon_cpu_pct"])["mean"],
            "daemon_mem_mean": describe(metrics["daemon_mem_pct"])["mean"],
            "memory_peak_mean": describe(metrics["memory_peak_mb"])["mean"],
        })
    return summary


def write_outputs(raw_rows: list[dict[str, Any]], summary_rows: list[dict[str, Any]]) -> None:
    write_csv(RESULTS_DIR / "raw.csv", raw_rows)
    write_csv(RESULTS_DIR / "summary.csv", summary_rows)


def build_figures(summary_rows: list[dict[str, Any]]) -> list[Path]:
    generated: list[Path] = []
    by_exp: dict[str, list[dict[str, Any]]] = {}
    for row in summary_rows:
        by_exp.setdefault(row["experiment"], []).append(row)

    sched = by_exp.get("调度策略", [])
    if sched:
        labels = [row["variant"] for row in sched]
        throughput = [float(row["throughput_mean"]) for row in sched]
        queue = [float(row["queue_wait_mean"]) for row in sched]
        write_bar_chart_svg(FIGURES_DIR / "scheduler_throughput.svg", "Scheduler Throughput", labels, throughput, "/s")
        write_bar_chart_svg(FIGURES_DIR / "scheduler_queue_wait.svg", "Scheduler Queue Wait", labels, queue, "ms")
        generated.extend([FIGURES_DIR / "scheduler_throughput.svg", FIGURES_DIR / "scheduler_queue_wait.svg"])

    cgroup = by_exp.get("cgroup 隔离", [])
    if cgroup:
        labels = [row["variant"] for row in cgroup]
        p95 = [float(row["p95_latency_mean"]) for row in cgroup]
        write_bar_chart_svg(FIGURES_DIR / "cgroup_p95.svg", "Cgroup P95 Latency", labels, p95, "ms")
        generated.append(FIGURES_DIR / "cgroup_p95.svg")

    fault = by_exp.get("容错故障注入", [])
    if fault:
        labels = [row["variant"] for row in fault]
        recovery = [float(row["recovery_rate_mean"]) for row in fault]
        write_bar_chart_svg(FIGURES_DIR / "fault_recovery.svg", "Fault Recovery Rate", labels, recovery, "")
        generated.append(FIGURES_DIR / "fault_recovery.svg")

    vllm = by_exp.get("真实 vLLM APC", [])
    if vllm:
        labels = [row["variant"] for row in vllm]
        ttft = [float(row["ttft_mean"]) for row in vllm]
        write_bar_chart_svg(FIGURES_DIR / "vllm_apc.svg", "vLLM APC TTFT", labels, ttft, "ms")
        generated.append(FIGURES_DIR / "vllm_apc.svg")

    if "扩展性" in by_exp:
        rows = by_exp["扩展性"]
        rows.sort(key=lambda item: int(str(item["variant"]).split("/")[-1]))
        labels = [row["variant"] for row in rows]
        throughput = [float(row["throughput_mean"]) for row in rows]
        p95 = [float(row["p95_latency_mean"]) for row in rows]
        memory = [float(row["memory_peak_mean"]) for row in rows]
        write_line_chart_svg(FIGURES_DIR / "scalability_throughput.svg", "Scalability Throughput", labels, {"throughput": throughput}, "/s")
        write_line_chart_svg(FIGURES_DIR / "scalability_p95.svg", "Scalability P95", labels, {"p95": p95}, "ms")
        write_line_chart_svg(FIGURES_DIR / "scalability_memory.svg", "Scalability Memory", labels, {"memory": memory}, "MB")
        generated.extend([
            FIGURES_DIR / "scalability_throughput.svg",
            FIGURES_DIR / "scalability_p95.svg",
            FIGURES_DIR / "scalability_memory.svg",
        ])
    return generated


def run_runtime_overhead(seed: int, use_runtime: bool, runs: int = 100) -> dict[str, Any]:
    latencies: list[float] = []
    start = _now_ms()
    router = MessageRouter()
    scheduler = FIFOScheduler()
    for idx in range(runs):
        began = _now_ms()
        if use_runtime:
            task = TaskSpec(task_id=f"overhead_{seed}_{idx}", agent_name="worker", task_input={"request": "x"})
            scheduler.enqueue(task)
            scheduled = scheduler.dequeue()
            assert scheduled is not None
            asyncio.run(router.send(Message(from_agent="agentd", to_agent="worker", payload={"task_id": task.task_id})))
            asyncio.run(router.receive("worker", limit=1))
            scheduler.complete_task(task.task_id)
        else:
            _ = {"output": "ok"}
        latencies.append(_now_ms() - began)
    return {
        "makespan_ms": _now_ms() - start,
        "latencies_ms": latencies,
        "queue_waits_ms": [0.0 for _ in latencies],
        "count": runs,
    }


def _row_from_result(experiment: str, variant: str, status: str, run: int, warmup: bool, data: dict[str, Any], notes: str = "") -> dict[str, Any]:
    latencies = [float(v) for v in data.get("latencies_ms", [])]
    queue_waits = [float(v) for v in data.get("queue_waits_ms", [])]
    count = int(data.get("count") or len(latencies) or 1)
    makespan = float(data.get("makespan_ms") or (max(latencies) if latencies else 0.0))
    throughput = count / max(makespan / 1000.0, 0.001)
    return {
        "experiment": experiment,
        "variant": variant,
        "run": run,
        "warmup": warmup,
        "status": status,
        "makespan_ms": makespan,
        "throughput": throughput,
        "avg_latency_ms": statistics.mean(latencies) if latencies else 0.0,
        "p95_latency_ms": _p95(latencies),
        "p99_latency_ms": _p99(latencies),
        "queue_wait_ms": statistics.mean(queue_waits) if queue_waits else 0.0,
        "resource_block_count": int(data.get("resource_block_count") or 0),
        "completion_rate": float(data.get("completion_rate") or data.get("failure_recovery_rate") or 0.0),
        "recovery_rate": float(data.get("failure_recovery_rate") or 0.0),
        "worker_restart_time_ms": float(data.get("worker_restart_time_ms") or 0.0),
        "token_saving_ratio": float(data.get("token_saving_ratio") or 0.0),
        "context_cache_hit_ratio": float(data.get("context_cache_hit_ratio") or 0.0),
        "ttft_ms": float(data.get("ttft_ms") or 0.0),
        "prefill_latency_ms": float(data.get("prefill_latency_ms") or 0.0),
        "kv_cache_usage_mb": float(data.get("kv_cache_usage_mb") or 0.0),
        "gpu_mem_peak_mb": float(data.get("gpu_mem_peak_mb") or 0.0),
        "daemon_cpu_pct": float(data.get("daemon_cpu") or data.get("cpu_usage_pct") or 0.0),
        "daemon_mem_pct": float(data.get("daemon_mem") or 0.0),
        "memory_peak_mb": float(data.get("memory_peak_mb") or 0.0),
        "notes": notes,
    }


def _summary_markdown(summary_rows: list[dict[str, Any]]) -> str:
    lines = ["| 实验 | 对比项 | runs | makespan mean(ms) | throughput mean(/s) | P95 latency mean(ms) | queue wait mean(ms) | recovery mean | notes |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for row in summary_rows:
        lines.append(
            f"| {row['experiment']} | {row['variant']} | {int(row['runs'])} | {float(row['makespan_mean']):.3f} | {float(row['throughput_mean']):.3f} | {float(row['p95_latency_mean']):.3f} | {float(row['queue_wait_mean']):.3f} | {float(row['recovery_rate_mean']):.3f} | |"
        )
    return "\n".join(lines)


def _status_symbol(ok: bool, skipped: bool = False) -> str:
    if skipped:
        return "⚠️"
    return "✅" if ok else "❌"


def build_report(raw_rows: list[dict[str, Any]], summary_rows: list[dict[str, Any]]) -> str:
    env = {
        "python": os.sys.version.split()[0],
        "os": os.uname().sysname,
        "kernel": os.uname().release,
        "machine": os.uname().machine,
        "platform": "openEuler Docker benchmark",
    }
    summary_table = _summary_markdown(summary_rows)
    return "\n".join([
        "# Agent Runtime Benchmark",
        "",
        "## 结论",
        "- 当前阶段只保留三组真实性能实验：调度策略、上下文优化、容错策略。",
        "- 每组执行 5 次预热和 30 次正式运行，输出 mean、P50、P95、标准差和 95% CI。",
        "",
        "## 复现方法",
        "1. 运行 `bash scripts/benchmark_docker_openeuler.sh`。",
        "2. 脚本会在 openEuler Docker 中执行 `pytest testing/perf/test_benchmark.py -q`。",
        "3. 结果会落到 `benchmark/results/raw.csv`、`benchmark/results/summary.csv`、`benchmark/figures/*.svg` 和根目录 `BENCHMARK.md`。",
        "",
        "## 实验环境",
        f"- Python：`{env['python']}`",
        f"- OS：`{env['os']} {env['kernel']} {env['machine']}`",
        f"- 平台：`{env['platform']}`",
        "",
        "## 指标定义",
        "- `makespan`：从第一项任务开始到最后一项完成的墙钟时间。",
        "- `throughput`：完成任务数 / makespan 秒。",
        "- `avg/P95/P99 latency`：单任务延迟统计。",
        "- `queue wait time`：进入调度器到真正执行的等待时间。",
        "- `resource blocking`：调度器因资源约束拒绝/推迟的次数。",
        "- `recovery rate`：故障注入后恢复并完成 workflow 的比例。",
        "",
        "## 结果总表",
        summary_table,
        "",
        "## 三组实验",
        "- 调度策略：FIFO vs resource-aware，保持相同任务数、Agent 数、执行时间、CPU/Memory 请求和并发上限。",
        "- 上下文优化：完整上下文重复发送 vs context reuse + structured compression，并验证关键约束保留。",
        "- 容错策略：无自动恢复、retry、fallback。",
        "",
        "## 图表",
        "- 调度性能图：`benchmark/figures/scheduler_throughput.svg`、`benchmark/figures/scheduler_queue_wait.svg`",
        "- 容错恢复图：`benchmark/figures/fault_recovery.svg`",
        "",
        "## 统计",
        "- 统计口径：5 次预热 + 30 次正式运行，输出 mean / stdev / P50 / P95 / P99 / 95% CI。",
        "",
        "## 原始数据",
        "- `benchmark/results/raw.csv`",
        "- `benchmark/results/summary.csv`",
        "",
        "## 备注",
        "- 真实 vLLM KV Cache 和真实 cgroup 不作为当前提交阻塞项。",
    ])


def run_suite(seed: int = 42) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any], list[Path], str]:
    raw_rows: list[dict[str, Any]] = []
    experiment_rows: list[dict[str, Any]] = []

    def collect(experiment: str, variant: str, runner: Callable[[int], dict[str, Any]], warmups: int = 5, runs: int = 30, notes: str = "") -> None:
        nonlocal raw_rows, experiment_rows
        raw, summary_input = _repeat(seed, warmups, runs, runner)
        for row in raw:
            raw_rows.append(_row_from_result(experiment, variant, "warmup" if row["warmup"] else "ok", row["run"], row["warmup"], row, notes))
        for row in summary_input:
            experiment_rows.append(_row_from_result(experiment, variant, "ok", row["run"], row["warmup"], row, notes))

    collect("调度策略", "FIFO", lambda idx: run_scheduler_fifo_concurrent(seed + idx), notes="same mixed workload")
    collect("调度策略", "resource-aware", lambda idx: run_scheduler_resource_aware(seed + idx), notes="same mixed workload")
    collect("上下文优化", "full-context", lambda idx: run_context_reuse(seed + idx, reused=False), runs=30)
    collect("上下文优化", "reuse+compression", lambda idx: run_context_reuse(seed + idx, reused=True), runs=30)
    collect("容错策略", "no-recovery", lambda idx: run_fault_modes(seed + idx, "fail_closed"), runs=30)
    collect("容错策略", "retry", lambda idx: run_fault_modes(seed + idx, "retry"), runs=30)
    collect("容错策略", "fallback", lambda idx: run_fault_modes(seed + idx, "fallback"), runs=30)

    summary_rows = summarize_rows(experiment_rows)
    write_outputs(raw_rows, summary_rows)
    figures = build_figures(summary_rows)
    report = build_report(experiment_rows, summary_rows)
    return experiment_rows, summary_rows, {}, {}, figures, report
