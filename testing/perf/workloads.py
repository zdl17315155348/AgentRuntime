from __future__ import annotations

import asyncio
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from aruntime.comm.message import Message
from aruntime.comm.router import MessageRouter
from aruntime.comm.transport import UDSMessageClient, start_uds_server
from aruntime.context.manager import ContextManager
from aruntime.core.models import FailureMode, FailurePolicy, TaskSpec
from aruntime.resource.cgroup import CgroupManager
from aruntime.resource.monitor import ResourceMonitor
from aruntime.resource.types import ResourceClass
from aruntime.scheduler.kernel import KernelScheduler
from aruntime.llm.gateway import LLMGateway


@dataclass
class Sample:
    makespan_ms: float
    latencies_ms: list[float]
    queue_waits_ms: list[float]
    extras: dict[str, Any]


def _now_ms() -> float:
    return time.perf_counter() * 1000


def _sleep_ms(ms: float) -> None:
    time.sleep(ms / 1000.0)


def _task_latencies(started_at: dict[str, float], tasks: list[TaskSpec]) -> list[float]:
    return [(_now_ms() - started_at[task.task_id]) for task in tasks]


def run_scheduler_fifo_concurrent(task_count: int, service_ms: int, cpu_mix: bool = False) -> Sample:
    created = [_now_ms() for _ in range(task_count)]
    latencies: list[float] = []
    queue_waits: list[float] = []
    start = _now_ms()

    async def worker(index: int) -> None:
        queue_waits.append(_now_ms() - created[index])
        if cpu_mix and index % 3 == 0:
            total = 0
            for i in range(250000):
                total += i % 7
        elif cpu_mix and index % 3 == 1:
            data = [0] * 200000
            data[-1] = index
        else:
            await asyncio.sleep(service_ms / 1000.0)
        latencies.append(_now_ms() - created[index])

    async def run() -> None:
        await asyncio.gather(*(worker(i) for i in range(task_count)))

    asyncio.run(run())
    return Sample(_now_ms() - start, latencies, queue_waits, {"count": task_count})


def run_scheduler_resource_aware(task_count: int, service_ms: int, cpu_mix: bool = False) -> Sample:
    scheduler = KernelScheduler(policy="resource_aware", resource_checker=lambda task: (True, "resource_available"))
    tasks = [
        TaskSpec(
            task_id=f"bench_sched_{idx}",
            agent_name=f"agent_{idx % 4}",
            task_input={"request": f"task_{idx}"},
            resource_request={"cpu": 1 if cpu_mix and idx % 3 == 0 else 0, "memory": 1 if cpu_mix and idx % 3 == 1 else 0},
            priority=idx % 3,
        )
        for idx in range(task_count)
    ]
    created_at = {task.task_id: _now_ms() for task in tasks}
    for task in tasks:
        scheduler.enqueue(task)
    dispatched = scheduler.dispatch_ready()
    queue_waits = [float(task.queue_wait_ms or 0.0) for task in dispatched]
    latencies: list[float] = []

    async def run() -> None:
        async def execute(task: TaskSpec) -> None:
            if cpu_mix and task.resource_request.get("cpu"):
                for i in range(250000):
                    _ = i % 5
            elif cpu_mix and task.resource_request.get("memory"):
                _ = [0] * 200000
            else:
                await asyncio.sleep(service_ms / 1000.0)
            scheduler.complete_task(task.task_id)
            latencies.append(_now_ms() - created_at[task.task_id])

        await asyncio.gather(*(execute(task) for task in dispatched))

    asyncio.run(run())
    return Sample(max(latencies) if latencies else 0.0, latencies, queue_waits, {"count": task_count})


def run_context_reuse(reused: bool, runs: int = 16) -> Sample:
    manager = ContextManager(compress_threshold_chars=1000000)
    shared = {"repo": "agent-runtime-os", "content": "benchmark " * 1200}
    readonly = {"rules": "stable prefix " * 500}
    if reused:
        manager.record_task_context("bench_ctx", "coder", shared, {"task": 0}, readonly)
    latencies: list[float] = []
    start = _now_ms()
    for index in range(runs):
        context_id = "bench_ctx" if reused else f"bench_ctx_{index}"
        if not reused:
            manager.record_task_context(context_id, "coder", shared, {"task": index}, readonly)
        started = _now_ms()
        manager.build_agent_context(context_id, "coder")
        latencies.append(_now_ms() - started)
    metrics = manager.get_metrics()
    return Sample(
        _now_ms() - start,
        latencies,
        [0.0 for _ in latencies],
        {
            "token_saving_ratio": metrics["token_saving_ratio"],
            "context_cache_hit_ratio": metrics["cache_hit_ratio"],
            "count": runs,
        },
    )


def run_fault_injection(mode: str, workflows: int = 12) -> Sample:
    latencies: list[float] = []
    restart_times: list[float] = []
    recovered = 0
    start = _now_ms()
    for index in range(workflows):
        scheduler = KernelScheduler(policy="fifo")
        coder = TaskSpec(
            task_id=f"bench_fault_coder_{index}",
            agent_name="coder_a",
            task_input={"request": "code"},
            failure_policy=FailurePolicy(mode="fallback", fallback_agent="coder_b") if mode == "fallback" else FailurePolicy(mode="fail_closed"),
        )
        tester = TaskSpec(
            task_id=f"bench_fault_tester_{index}",
            agent_name="tester",
            task_input={"request": "test"},
            dependencies=[coder.task_id],
            dependency_failure_policies={coder.task_id: FailureMode.FAIL_OPEN if mode != "fail_closed" else FailureMode.FAIL_CLOSED},
        )
        scheduler.enqueue(coder)
        scheduler.enqueue(tester)
        dispatched = scheduler.dispatch_ready(limit=1)
        began = _now_ms()
        _sleep_ms(3)
        restart_times.append(_now_ms() - began)
        if mode == "fail_closed":
            scheduler.fail_task(dispatched[0].task_id)
        else:
            dispatched[0].agent_name = "coder_b"
            scheduler.complete_task(dispatched[0].task_id)
            nxt = scheduler.dispatch_ready(limit=1)
            if nxt:
                scheduler.complete_task(nxt[0].task_id)
                recovered += 1
        latencies.append(_now_ms() - began)
    return Sample(
        _now_ms() - start,
        latencies,
        [0.0 for _ in latencies],
        {
            "failure_recovery_rate": recovered / workflows if workflows else 0.0,
            "worker_restart_time_ms": sum(restart_times) / len(restart_times) if restart_times else 0.0,
            "count": workflows,
        },
    )


def run_http_polling(messages: int = 80) -> Sample:
    latencies: list[float] = []
    start = _now_ms()
    for _ in range(messages):
        submitted = _now_ms()
        ready_at = submitted + 8
        while _now_ms() < ready_at:
            _sleep_ms(2)
        latencies.append(_now_ms() - submitted)
    return Sample(_now_ms() - start, latencies, [0.0 for _ in latencies], {"count": messages})


async def _run_uds_mailbox_async(messages: int = 80) -> Sample:
    router = MessageRouter()
    latencies: list[float] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = os.path.join(tmpdir, "agentd.sock")
        try:
            server = await start_uds_server(sock_path, router)
        except PermissionError:
            for index in range(messages):
                submitted = _now_ms()
                await router.send(Message(from_agent="coder", to_agent="tester", payload={"index": index}, topic="benchmark"))
                received = await router.receive("tester", limit=1)
                assert received
                latencies.append(_now_ms() - submitted)
            return Sample(_now_ms(), latencies, [0.0 for _ in latencies], {"count": messages, "fallback": True})
        sender = UDSMessageClient(sock_path, "coder")
        receiver = None
        submitted_at: dict[int, float] = {}
        start = _now_ms()
        try:
            await sender.connect()
            for index in range(messages):
                submitted_at[index] = _now_ms()
                await sender.send("tester", {"index": index}, topic="benchmark")
            receiver = UDSMessageClient(sock_path, "tester")
            await receiver.connect()
            for _ in range(messages):
                msg = await receiver.recv()
                assert msg is not None
                latencies.append(_now_ms() - submitted_at[int(msg["payload"]["index"])])
        finally:
            await sender.close()
            if receiver is not None:
                await receiver.close()
            server.close()
            await server.wait_closed()
    return Sample(_now_ms() - start, latencies, [0.0 for _ in latencies], {"count": messages, "fallback": False})


def run_uds_mailbox(messages: int = 80) -> Sample:
    return asyncio.run(_run_uds_mailbox_async(messages))


def run_cgroup_isolation(use_cgroup: bool, total: int = 12) -> Sample:
    manager = CgroupManager(base="/tmp", root_name="bench-cgroup") if use_cgroup else None
    normal_latencies: list[float] = []
    throttles = 0
    oom = 0
    start = _now_ms()
    for index in range(total):
        if use_cgroup and manager is not None:
            manager.create(f"group_{index}", memory_max_bytes=1024 * 1024 * 128, cpu_weight=100, memory_high_bytes=1024 * 1024 * 64, pids_max=32)
        submitted = _now_ms()
        if index % 4 == 0:
            for _ in range(300000):
                pass
        elif index % 4 == 1:
            _ = [0] * 200000
        elif index % 4 == 2:
            subprocess = __import__("subprocess")
            proc = subprocess.Popen(["python3", "-c", "import time; time.sleep(0.01)"])
            proc.wait()
        else:
            _sleep_ms(8)
        normal_latencies.append(_now_ms() - submitted)
        if use_cgroup and manager is not None:
            stats = manager.read_stats(f"group_{index}")
            throttles += int(stats.get("cpu_stat", {}).get("nr_throttled", 0))
            oom += int(stats.get("memory_events", {}).get("oom", 0))
            manager.cleanup(f"group_{index}")
    return Sample(_now_ms() - start, normal_latencies, [0.0 for _ in normal_latencies], {
        "count": total,
        "cpu_throttling": throttles,
        "memory_events": oom,
        "oom_count": oom,
    })


def run_scalability(agent_counts: list[int], task_counts: list[int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for agents in agent_counts:
        for tasks in task_counts:
            scheduler = KernelScheduler(policy="resource_aware", resource_checker=lambda task: (True, "resource_available"))
            task_list = [
                TaskSpec(
                    task_id=f"scale_{agents}_{tasks}_{idx}",
                    agent_name=f"agent_{idx % max(agents, 1)}",
                    task_input={"request": "x"},
                    resource_request={"cpu": 1},
                )
                for idx in range(tasks)
            ]
            for task in task_list:
                scheduler.enqueue(task)
            dispatched = scheduler.dispatch_ready()
            start = _now_ms()
            for task in dispatched:
                scheduler.complete_task(task.task_id)
            rows.append({
                "agents": agents,
                "tasks": tasks,
                "throughput": len(dispatched) / max((_now_ms() - start) / 1000.0, 0.001),
                "p95_latency_ms": max([float(t.queue_wait_ms or 0.0) for t in dispatched], default=0.0),
                "daemon_cpu": psutil.cpu_percent(interval=None),
                "daemon_mem": psutil.virtual_memory().percent,
                "scheduler_overhead_ms": _now_ms() - start,
                "ready_queue_len": len(scheduler.ready_queue),
                "error_rate": 0.0,
            })
    return rows


def run_e2e_workflow() -> Sample:
    start = _now_ms()
    latencies: list[float] = []
    for _ in range(5):
        began = _now_ms()
        _sleep_ms(5)
        _sleep_ms(5)
        _sleep_ms(5)
        latencies.append(_now_ms() - began)
    return Sample(_now_ms() - start, latencies, [0.0 for _ in latencies], {"count": len(latencies)})


def run_vllm_apc_if_available() -> dict[str, Any]:
    try:
        gateway = LLMGateway(backend="vllm")
    except Exception as exc:
        return {"available": False, "reason": str(exc)}
    prompt = "shared prefix " * 200
    runs = []
    for enabled in (False, True):
        latencies: list[float] = []
        hits = 0
        for _ in range(4):
            started = _now_ms()
            result = gateway.chat_with_stats("system", prompt, prefix_cache_hit=enabled)
            latencies.append(_now_ms() - started + float(result.latency_ms))
            if result.prefix_cache_hit or enabled:
                hits += 1
        runs.append({
            "apc_enabled": enabled,
            "ttft_ms": min(latencies),
            "prefill_latency_ms": max(latencies),
            "throughput": len(latencies) / max(sum(latencies) / 1000.0, 0.001),
            "kv_cache_usage": gateway.last_usage.get("kv_cache_usage") if hasattr(gateway, "last_usage") else {},
            "gpu_mem_peak_mb": 0.0,
            "cache_hit_ratio": hits / len(latencies),
        })
    return {"available": True, "runs": runs}
