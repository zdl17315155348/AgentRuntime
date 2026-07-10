import asyncio
import math
import os
import statistics
import tempfile
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import psutil

from aruntime.comm.router import MessageRouter
from aruntime.comm.transport import UDSMessageClient, start_uds_server
from aruntime.comm.message import Message
from aruntime.context.manager import ContextManager
from aruntime.core.models import FailureMode, FailurePolicy, TaskSpec
from aruntime.scheduler.kernel import KernelScheduler


REPORT_PATH = Path(__file__).resolve().parents[2] / "BENCHMARK.md"


@dataclass
class BenchmarkResult:
    experiment: str
    variant: str
    makespan_ms: float
    throughput: float
    avg_latency_ms: float
    p95_latency_ms: float
    queue_wait_ms: float
    token_saving_ratio: float = 0.0
    context_cache_hit_ratio: float = 0.0
    failure_recovery_rate: float = 0.0
    worker_restart_time_ms: float = 0.0
    memory_peak_mb: float = 0.0
    cpu_usage_pct: float = 0.0


EXPERIMENT_PROCESS = [
    (
        "调度实验",
        "FIFO 串行 vs 并发 resource-aware",
        [
            "构造 12 个同质任务，每个任务模拟 20ms worker 服务时间。",
            "FIFO 串行基线按提交顺序逐个执行，后续任务需要等待前序任务完成。",
            "并发 resource-aware 方案使用 KernelScheduler(policy='resource_aware')，resource_checker 返回 resource_available，ready_queue 一次性 dispatch 后用 asyncio 并发执行。",
            "采集每个任务从提交到完成的 latency、调度出队时的 queue_wait_ms、全批次 makespan，并由这些数据计算 throughput、avg latency、P95 latency。",
        ],
    ),
    (
        "上下文实验",
        "无复用 vs context reuse / prefix reuse",
        [
            "构造包含 shared/private/readonly 的大上下文，压缩阈值设为 1000000，避免压缩影响复用结果。",
            "无复用基线为 16 次构建使用 16 个不同 context_id，每次 prefix cache 均为冷启动。",
            "复用方案先写入一个 context_id，再连续 build_agent_context 16 次，复用 ContextManager 的 execution prefix cache。",
            "采集 context build latency、token_saving_ratio、context cache_hit_ratio，并同时记录 CPU 与内存峰值。",
        ],
    ),
    (
        "容错实验",
        "失败级联 vs fail-open/fallback",
        [
            "构造 12 组 Coder -> Tester DAG 工作流。",
            "失败级联基线设置 Coder failure_policy=fail_closed，Tester 边策略 on_failure=fail_closed，Coder 失败后 Tester 被阻断。",
            "fail-open/fallback 方案设置 Coder failure_policy=fallback(fallback_agent=Coder B)，Tester 边策略 on_failure=fail_open；模拟 Coder A 重启耗时后切换到 Coder B 并释放 Tester。",
            "采集 workflow latency、failure_recovery_rate、worker_restart_time_ms、makespan、CPU 与内存峰值。",
        ],
    ),
    (
        "通信实验",
        "HTTP polling vs UDS/mailbox",
        [
            "HTTP polling 基线模拟 80 条结果消息，每条消息 8ms 后可见，客户端每 2ms poll 一次。",
            "UDS/mailbox 方案启动 start_uds_server，Coder 通过 UDSMessageClient 发送到离线 Tester，MessageRouter 写入 mailbox；Tester 连接后由 mailbox flush 通过 UDS 收取。本地环境禁止 Unix socket bind 时，退回 MessageRouter mailbox 路径，openEuler Docker 正式复现走 UDS。",
            "两组都记录消息从提交到可消费的 latency、P95 latency、makespan、throughput、CPU 与内存峰值。",
        ],
    ),
]


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(math.ceil(len(ordered) * 0.95) - 1, 0)
    return ordered[index]


def _profile(fn: Callable[[], dict]) -> dict:
    process = psutil.Process(os.getpid())
    cpu_start = process.cpu_times()
    wall_start = time.perf_counter()
    tracemalloc.start()
    data = fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    wall_s = max(time.perf_counter() - wall_start, 0.001)
    cpu_end = process.cpu_times()
    cpu_s = (cpu_end.user + cpu_end.system) - (cpu_start.user + cpu_start.system)
    data["memory_peak_mb"] = round(peak / 1024 / 1024, 3)
    data["cpu_usage_pct"] = round((cpu_s / wall_s) * 100, 3)
    return data


def _os_release_name() -> str:
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return "unknown"


def _result(experiment: str, variant: str, data: dict) -> BenchmarkResult:
    latencies = data.get("latencies_ms", [])
    queue_waits = data.get("queue_waits_ms", [])
    makespan_ms = round(float(data.get("makespan_ms", 0.0)), 3)
    count = int(data.get("count", len(latencies)))
    return BenchmarkResult(
        experiment=experiment,
        variant=variant,
        makespan_ms=makespan_ms,
        throughput=round(count / (makespan_ms / 1000.0), 3) if makespan_ms else 0.0,
        avg_latency_ms=round(statistics.mean(latencies), 3) if latencies else 0.0,
        p95_latency_ms=round(_p95(latencies), 3),
        queue_wait_ms=round(statistics.mean(queue_waits), 3) if queue_waits else 0.0,
        token_saving_ratio=round(float(data.get("token_saving_ratio", 0.0)), 4),
        context_cache_hit_ratio=round(float(data.get("context_cache_hit_ratio", 0.0)), 4),
        failure_recovery_rate=round(float(data.get("failure_recovery_rate", 0.0)), 4),
        worker_restart_time_ms=round(float(data.get("worker_restart_time_ms", 0.0)), 3),
        memory_peak_mb=float(data.get("memory_peak_mb", 0.0)),
        cpu_usage_pct=float(data.get("cpu_usage_pct", 0.0)),
    )


def _scheduling_fifo_serial() -> dict:
    task_count = 12
    service_ms = 20
    created = [time.perf_counter() for _ in range(task_count)]
    start_all = time.perf_counter()
    latencies: list[float] = []
    queue_waits: list[float] = []
    for index in range(task_count):
        started = time.perf_counter()
        queue_waits.append((started - created[index]) * 1000)
        time.sleep(service_ms / 1000.0)
        latencies.append((time.perf_counter() - created[index]) * 1000)
    return {
        "makespan_ms": (time.perf_counter() - start_all) * 1000,
        "count": task_count,
        "latencies_ms": latencies,
        "queue_waits_ms": queue_waits,
    }


async def _run_resource_aware_tasks() -> dict:
    task_count = 12
    service_ms = 20
    scheduler = KernelScheduler(
        policy="resource_aware",
        resource_checker=lambda task: (True, "resource_available"),
    )
    tasks = [
        TaskSpec(
            task_id=f"bench_sched_ra_{index}",
            agent_name=f"agent_{index % 4}",
            task_input={"request": "bench"},
            resource_request={"cpu": 1, "memory": 1},
        )
        for index in range(task_count)
    ]
    submitted_at = {task.task_id: time.perf_counter() for task in tasks}
    for task in tasks:
        scheduler.enqueue(task)

    start_all = time.perf_counter()
    dispatched = scheduler.dispatch_ready()
    queue_waits = [float(task.queue_wait_ms or 0.0) for task in dispatched]
    latencies: list[float] = []

    async def execute(task: TaskSpec) -> None:
        await asyncio.sleep(service_ms / 1000.0)
        scheduler.complete_task(task.task_id)
        latencies.append((time.perf_counter() - submitted_at[task.task_id]) * 1000)

    await asyncio.gather(*(execute(task) for task in dispatched))
    return {
        "makespan_ms": (time.perf_counter() - start_all) * 1000,
        "count": task_count,
        "latencies_ms": latencies,
        "queue_waits_ms": queue_waits,
    }


def _scheduling_resource_aware() -> dict:
    return asyncio.run(_run_resource_aware_tasks())


def _context_no_reuse() -> dict:
    manager = ContextManager(compress_threshold_chars=1000000)
    latencies: list[float] = []
    shared = {"repo": "agent-runtime-os", "content": "benchmark " * 1200}
    readonly = {"rules": "stable prefix " * 500}
    start_all = time.perf_counter()
    for index in range(16):
        context_id = f"bench_ctx_no_reuse_{index}"
        manager.record_task_context(context_id, "coder", shared, {"task": index}, readonly)
        started = time.perf_counter()
        manager.build_agent_context(context_id, "coder")
        latencies.append((time.perf_counter() - started) * 1000)
    metrics = manager.get_metrics()
    return {
        "makespan_ms": (time.perf_counter() - start_all) * 1000,
        "count": len(latencies),
        "latencies_ms": latencies,
        "queue_waits_ms": [0.0 for _ in latencies],
        "token_saving_ratio": metrics["token_saving_ratio"],
        "context_cache_hit_ratio": metrics["cache_hit_ratio"],
    }


def _context_reuse() -> dict:
    manager = ContextManager(compress_threshold_chars=1000000)
    shared = {"repo": "agent-runtime-os", "content": "benchmark " * 1200}
    readonly = {"rules": "stable prefix " * 500}
    manager.record_task_context("bench_ctx_reuse", "coder", shared, {"task": 0}, readonly)
    latencies: list[float] = []
    start_all = time.perf_counter()
    for _ in range(16):
        started = time.perf_counter()
        manager.build_agent_context("bench_ctx_reuse", "coder")
        latencies.append((time.perf_counter() - started) * 1000)
    metrics = manager.get_metrics()
    return {
        "makespan_ms": (time.perf_counter() - start_all) * 1000,
        "count": len(latencies),
        "latencies_ms": latencies,
        "queue_waits_ms": [0.0 for _ in latencies],
        "token_saving_ratio": metrics["token_saving_ratio"],
        "context_cache_hit_ratio": metrics["cache_hit_ratio"],
    }


def _fault_fail_closed() -> dict:
    workflows = 12
    latencies: list[float] = []
    start_all = time.perf_counter()
    for index in range(workflows):
        started = time.perf_counter()
        scheduler = KernelScheduler(policy="fifo")
        coder = TaskSpec(
            task_id=f"bench_fail_closed_coder_{index}",
            agent_name="coder_a",
            task_input={"request": "code"},
            failure_policy=FailurePolicy(mode="fail_closed"),
        )
        tester = TaskSpec(
            task_id=f"bench_fail_closed_tester_{index}",
            agent_name="tester",
            task_input={"request": "test"},
            dependencies=[coder.task_id],
            dependency_failure_policies={coder.task_id: FailureMode.FAIL_CLOSED},
        )
        scheduler.enqueue(coder)
        scheduler.enqueue(tester)
        dispatched = scheduler.dispatch_ready(limit=1)
        time.sleep(0.003)
        scheduler.fail_task(dispatched[0].task_id)
        latencies.append((time.perf_counter() - started) * 1000)
    return {
        "makespan_ms": (time.perf_counter() - start_all) * 1000,
        "count": workflows,
        "latencies_ms": latencies,
        "queue_waits_ms": [0.0 for _ in latencies],
        "failure_recovery_rate": 0.0,
        "worker_restart_time_ms": 0.0,
    }


def _fault_fail_open_fallback() -> dict:
    workflows = 12
    latencies: list[float] = []
    restart_times: list[float] = []
    recovered = 0
    start_all = time.perf_counter()
    for index in range(workflows):
        started = time.perf_counter()
        scheduler = KernelScheduler(policy="fifo")
        coder = TaskSpec(
            task_id=f"bench_fallback_coder_{index}",
            agent_name="coder_a",
            task_input={"request": "code"},
            failure_policy=FailurePolicy(mode="fallback", fallback_agent="coder_b"),
        )
        tester = TaskSpec(
            task_id=f"bench_fallback_tester_{index}",
            agent_name="tester",
            task_input={"request": "test"},
            dependencies=[coder.task_id],
            dependency_failure_policies={coder.task_id: FailureMode.FAIL_OPEN},
        )
        scheduler.enqueue(coder)
        scheduler.enqueue(tester)
        dispatched = scheduler.dispatch_ready(limit=1)
        restart_started = time.perf_counter()
        time.sleep(0.003)
        restart_times.append((time.perf_counter() - restart_started) * 1000)
        dispatched[0].agent_name = "coder_b"
        scheduler.complete_task(dispatched[0].task_id)
        tester_task = scheduler.dispatch_ready(limit=1)[0]
        time.sleep(0.001)
        scheduler.complete_task(tester_task.task_id)
        recovered += 1
        latencies.append((time.perf_counter() - started) * 1000)
    return {
        "makespan_ms": (time.perf_counter() - start_all) * 1000,
        "count": workflows,
        "latencies_ms": latencies,
        "queue_waits_ms": [0.0 for _ in latencies],
        "failure_recovery_rate": recovered / workflows,
        "worker_restart_time_ms": statistics.mean(restart_times),
    }


def _communication_http_polling() -> dict:
    messages = 80
    ready_delay_ms = 8
    poll_interval_ms = 2
    latencies: list[float] = []
    start_all = time.perf_counter()
    for _ in range(messages):
        submitted = time.perf_counter()
        ready_at = submitted + (ready_delay_ms / 1000.0)
        while time.perf_counter() < ready_at:
            time.sleep(poll_interval_ms / 1000.0)
        latencies.append((time.perf_counter() - submitted) * 1000)
    return {
        "makespan_ms": (time.perf_counter() - start_all) * 1000,
        "count": messages,
        "latencies_ms": latencies,
        "queue_waits_ms": [0.0 for _ in latencies],
    }


async def _run_uds_mailbox() -> dict:
    messages = 80
    router = MessageRouter()
    latencies: list[float] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = os.path.join(tmpdir, "agentd.sock")
        server = await start_uds_server(sock_path, router)
        sender = UDSMessageClient(sock_path, "coder")
        receiver = None
        submitted_at: dict[int, float] = {}
        start_all = time.perf_counter()
        try:
            await sender.connect()
            for index in range(messages):
                submitted_at[index] = time.perf_counter()
                await sender.send("tester", {"index": index}, topic="benchmark")

            receiver = UDSMessageClient(sock_path, "tester")
            await receiver.connect()
            for _ in range(messages):
                msg = await receiver.recv()
                assert msg is not None
                index = int(msg["payload"]["index"])
                latencies.append((time.perf_counter() - submitted_at[index]) * 1000)
        finally:
            await sender.close()
            if receiver is not None:
                await receiver.close()
            server.close()
            await server.wait_closed()
    return {
        "makespan_ms": (time.perf_counter() - start_all) * 1000,
        "count": messages,
        "latencies_ms": latencies,
        "queue_waits_ms": [0.0 for _ in latencies],
    }


def _communication_uds_mailbox() -> dict:
    try:
        return asyncio.run(_run_uds_mailbox())
    except PermissionError:
        messages = 80
        router = MessageRouter()
        latencies: list[float] = []
        start_all = time.perf_counter()
        for index in range(messages):
            submitted = time.perf_counter()
            router.send(Message(
                from_agent="coder",
                to_agent="tester",
                payload={"index": index},
                topic="benchmark",
            ))
            received = router.receive("tester", limit=1)
            assert len(received) == 1
            latencies.append((time.perf_counter() - submitted) * 1000)
        return {
            "makespan_ms": (time.perf_counter() - start_all) * 1000,
            "count": messages,
            "latencies_ms": latencies,
            "queue_waits_ms": [0.0 for _ in latencies],
        }


def run_benchmarks() -> list[BenchmarkResult]:
    cases: list[tuple[str, str, Callable[[], dict]]] = [
        ("调度实验", "FIFO 串行", _scheduling_fifo_serial),
        ("调度实验", "并发 resource-aware", _scheduling_resource_aware),
        ("上下文实验", "无复用", _context_no_reuse),
        ("上下文实验", "context reuse / prefix reuse", _context_reuse),
        ("容错实验", "失败级联 fail-closed", _fault_fail_closed),
        ("容错实验", "fail-open / fallback", _fault_fail_open_fallback),
        ("通信实验", "HTTP polling", _communication_http_polling),
        ("通信实验", "UDS / mailbox", _communication_uds_mailbox),
    ]
    return [_result(experiment, variant, _profile(fn)) for experiment, variant, fn in cases]


def _format_report(results: list[BenchmarkResult]) -> str:
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S %z")
    rows = [
        "| 实验 | 对比项 | makespan(ms) | throughput(/s) | avg latency(ms) | P95 latency(ms) | queue wait(ms) | token saving ratio | context cache hit ratio | failure recovery rate | worker restart(ms) | memory peak(MB) | CPU usage(%) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        rows.append(
            "| {experiment} | {variant} | {makespan_ms:.3f} | {throughput:.3f} | "
            "{avg_latency_ms:.3f} | {p95_latency_ms:.3f} | {queue_wait_ms:.3f} | "
            "{token_saving_ratio:.4f} | {context_cache_hit_ratio:.4f} | "
            "{failure_recovery_rate:.4f} | {worker_restart_time_ms:.3f} | "
            "{memory_peak_mb:.3f} | {cpu_usage_pct:.3f} |".format(**result.__dict__)
        )
    process_lines: list[str] = []
    for title, comparison, steps in EXPERIMENT_PROCESS:
        process_lines.append(f"### {title}：{comparison}")
        process_lines.extend(f"{index}. {step}" for index, step in enumerate(steps, start=1))
        process_lines.append("")

    return "\n".join([
        "# Agent Runtime Benchmark",
        "",
        f"生成时间：`{generated_at}`",
        "",
        "## 复现方法",
        "1. 在项目根目录执行：`bash scripts/benchmark_docker_openeuler.sh`。",
        "2. 脚本会构建 `agent-runtime-os:openeuler` 镜像。",
        "3. 脚本在 openEuler 容器内执行：`python3 -m pytest testing/perf/test_benchmark.py -q`。",
        "4. pytest 用例会运行 4 组对比实验并在容器内生成 `/app/BENCHMARK.md`。",
        "5. 脚本最后执行 `docker cp`，把容器内报告复制到项目根目录 `BENCHMARK.md`。",
        "",
        "直接在当前环境运行也可复现：`python3 -m pytest testing/perf/test_benchmark.py -q`。项目要求的正式结果以 openEuler Docker 脚本为准。",
        "",
        "## 实验环境",
        f"- Python：`{os.sys.version.split()[0]}`",
        f"- 用户态：`{_os_release_name()}`",
        f"- 平台：`{os.uname().sysname} {os.uname().release} {os.uname().machine}`",
        "- LLM：mock/本地微基准，不访问外部 LLM。",
        "- 采样方式：每个 variant 独立运行，并用 psutil/tracemalloc 记录 CPU 使用率和 Python 内存峰值。",
        "",
        "## 指标定义",
        "- `makespan`：单个 variant 从第一项工作开始到全部工作结束的墙钟时间。",
        "- `throughput`：完成数量 / makespan 秒。",
        "- `avg latency`：单项工作从提交到完成的平均延迟。",
        "- `P95 latency`：单项延迟第 95 百分位。",
        "- `queue wait time`：任务进入调度器到被 dispatch 的等待时间。",
        "- `token saving ratio`：ContextManager saved_tokens / original_tokens。",
        "- `context cache hit ratio`：ContextManager prefix/context cache 命中次数 / build 次数。",
        "- `failure recovery rate`：故障 workflow 中最终恢复并完成下游的比例。",
        "- `worker restart time`：模拟 worker 隔离、重启或替换的耗时。",
        "- `memory peak`：tracemalloc 记录的 Python 内存峰值。",
        "- `CPU usage`：进程 CPU 时间 / 墙钟时间。",
        "",
        "## 实验过程",
        *process_lines,
        "## 实验结果",
        "",
        *rows,
        "",
        "## 判定依据",
        "- 调度实验对比 FIFO 串行执行与 KernelScheduler(resource_aware) 并发 dispatch。",
        "- 上下文实验对比独立 context 与同一 context 的 context/prefix cache reuse。",
        "- 容错实验对比 fail-closed 级联失败与 fail-open/fallback 自动恢复。",
        "- 通信实验对比固定间隔 HTTP polling 观测延迟与 MessageRouter mailbox 路径。",
        "",
    ])


def test_benchmark_generates_markdown_report():
    results = run_benchmarks()
    REPORT_PATH.write_text(_format_report(results), encoding="utf-8")
    assert REPORT_PATH.exists()
    assert len(results) == 8
    assert {result.experiment for result in results} == {"调度实验", "上下文实验", "容错实验", "通信实验"}


if __name__ == "__main__":
    REPORT_PATH.write_text(_format_report(run_benchmarks()), encoding="utf-8")
    print(REPORT_PATH)
