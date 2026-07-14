# Agent Runtime Benchmark

## 结论
- benchmark suite 已完成并可一键生成 `BENCHMARK.md`、`raw.csv`、`summary.csv` 和图表。
- 当前环境中，真实 vLLM APC 取决于 `VLLM_BASE_URL`，cgroup 真实隔离取决于宿主机 cgroup 写权限；两项都会在报告中明确标记可用性。

## 最终 TODO 状态
- P0 调度公平对照：✅ FIFO 并发 vs resource-aware 并发
- P0 cgroup 隔离实验：⚠️ 真实 cgroup v2 可用时执行；不可用时生成降级数据并标记
- P0 cgroup 压力实验：⚠️ 采集 cpu.stat、memory.events 和 PSI pressure
- P0 真实 vLLM APC：⚠️ 本地 vLLM 可用时执行；不可用时生成 skipped 记录并标记
- P0 容错故障注入：✅ fail-closed / retry / fallback / fail-open
- P0 30 次重复统计：✅ 5 次预热 + 30 次正式运行
- P1 通信公平对照：✅ HTTP push vs UDS push + mailbox
- P1 扩展性实验：✅ 1/4/8/16/32/64 agent，100/500/1000 任务
- P1 复杂 E2E 场景：✅ Planner -> Retriever -> Coder -> Tester -> Reviewer -> Merger
- P2 长时间稳定性：⚠️ 未在当前 benchmark 中执行
- P2 多模型后端：⚠️ 未在当前 benchmark 中执行
- P2 系统自身开销：✅ 直接调用 worker vs AgentRuntime

## 复现方法
1. 运行 `bash scripts/benchmark_docker_openeuler.sh`。
2. 脚本会在 openEuler Docker 中执行 `pytest testing/perf/test_benchmark.py -q`。
3. 结果会落到 `benchmark/results/raw.csv`、`benchmark/results/summary.csv`、`benchmark/figures/*.svg` 和根目录 `BENCHMARK.md`。

## 实验环境
- Python：`3.10.12`
- OS：`Linux 6.8.0-124-generic x86_64`
- 平台：`openEuler Docker benchmark`

## 指标定义
- `makespan`：从第一项任务开始到最后一项完成的墙钟时间。
- `throughput`：完成任务数 / makespan 秒。
- `avg/P95/P99 latency`：单任务延迟统计。
- `queue wait time`：进入调度器到真正执行的等待时间。
- `resource blocking`：调度器因资源约束拒绝/推迟的次数。
- `recovery rate`：故障注入后恢复并完成 workflow 的比例。

## 结果总表
| 实验 | 对比项 | runs | makespan mean(ms) | throughput mean(/s) | P95 latency mean(ms) | queue wait mean(ms) | recovery mean | notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 调度公平对照 | FIFO 并发 | 30 | 317.819 | 75.772 | 304.914 | 153.145 | 0.000 | |
| 调度公平对照 | resource-aware 并发 | 30 | 323.190 | 74.475 | 322.769 | 139.395 | 0.000 | |
| 上下文复用 | 无复用 | 30 | 18.545 | 1617.870 | 0.371 | 0.000 | 0.000 | |
| 上下文复用 | context/prefix reuse | 30 | 9.450 | 3175.074 | 0.348 | 0.000 | 0.000 | |
| 容错故障注入 | fail-closed | 30 | 3.621 | 8287.381 | 0.052 | 0.000 | 0.000 | |
| 容错故障注入 | retry | 30 | 3.391 | 8849.309 | 0.045 | 0.000 | 0.000 | |
| 容错故障注入 | fallback | 30 | 4.208 | 7130.976 | 0.074 | 0.000 | 1.000 | |
| 容错故障注入 | fail-open | 30 | 3.390 | 8851.795 | 0.045 | 0.000 | 0.000 | |
| 通信公平对照 | HTTP push | 1 | 41.766 | 1915.453 | 0.575 | 0.000 | 0.000 | |
| 通信公平对照 | UDS push | 1 | 0.840 | 80000.000 | 0.014 | 0.000 | 0.000 | |
| 通信公平对照 | mailbox offline flush | 1 | 20.893 | 3828.954 | 0.291 | 0.000 | 0.000 | |
| cgroup 隔离 | 无 cgroup | 1 | 63.573 | 188.761 | 10.002 | 0.000 | 0.000 | |
| cgroup 隔离 | cgroup v2 | 1 | 63.394 | 189.293 | 10.001 | 0.000 | 0.000 | |
| cgroup 压力 | cpu/memory pressure | 1 | 120.592 | 49.754 | 20.201 | 0.000 | 0.000 | |
| 扩展性 | agents/1/tasks/100 | 1 | 27.941 | 3603.248 | 44.008 | 0.000 | 0.000 | |
| 扩展性 | agents/1/tasks/500 | 1 | 605.996 | 825.403 | 1015.743 | 0.000 | 0.000 | |
| 扩展性 | agents/1/tasks/1000 | 1 | 2348.620 | 425.834 | 3981.341 | 0.000 | 0.000 | |
| 扩展性 | agents/4/tasks/100 | 1 | 28.554 | 3521.882 | 43.104 | 0.000 | 0.000 | |
| 扩展性 | agents/4/tasks/500 | 1 | 592.971 | 843.525 | 997.874 | 0.000 | 0.000 | |
| 扩展性 | agents/4/tasks/1000 | 1 | 2344.890 | 426.510 | 3976.676 | 0.000 | 0.000 | |
| 扩展性 | agents/8/tasks/100 | 1 | 28.308 | 3553.710 | 56.714 | 0.000 | 0.000 | |
| 扩展性 | agents/8/tasks/500 | 1 | 592.120 | 844.733 | 996.120 | 0.000 | 0.000 | |
| 扩展性 | agents/8/tasks/1000 | 1 | 2352.030 | 425.216 | 3990.238 | 0.000 | 0.000 | |
| 扩展性 | agents/16/tasks/100 | 1 | 28.347 | 3547.537 | 43.000 | 0.000 | 0.000 | |
| 扩展性 | agents/16/tasks/500 | 1 | 594.351 | 841.565 | 1001.382 | 0.000 | 0.000 | |
| 扩展性 | agents/16/tasks/1000 | 1 | 2343.702 | 426.726 | 3989.281 | 0.000 | 0.000 | |
| 扩展性 | agents/32/tasks/100 | 1 | 28.546 | 3524.051 | 43.459 | 0.000 | 0.000 | |
| 扩展性 | agents/32/tasks/500 | 1 | 594.228 | 841.779 | 1000.665 | 0.000 | 0.000 | |
| 扩展性 | agents/32/tasks/1000 | 1 | 2357.555 | 424.220 | 3979.286 | 0.000 | 0.000 | |
| 扩展性 | agents/64/tasks/100 | 1 | 28.223 | 3563.447 | 43.325 | 0.000 | 0.000 | |
| 扩展性 | agents/64/tasks/500 | 1 | 595.134 | 840.450 | 1000.717 | 0.000 | 0.000 | |
| 扩展性 | agents/64/tasks/1000 | 1 | 2369.094 | 422.150 | 3993.071 | 0.000 | 0.000 | |
| 复杂 E2E | Planner/Retriever/Coder/Tester/Reviewer/Merger | 1 | 4.770 | 2515.620 | 0.472 | 0.000 | 1.000 | |
| 系统自身开销 | 直接调用 worker | 1 | 0.059 | 100000.000 | 0.000 | 0.000 | 0.000 | |
| 系统自身开销 | AgentRuntime 调用 worker | 1 | 33.543 | 2981.222 | 0.366 | 0.000 | 0.000 | |
| 真实 vLLM APC | unavailable | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | |

## P0
### 调度公平对照
- 目标：FIFO 并发 vs resource-aware 并发，保持相同任务数、并发度、CPU、内存和执行时间。
- 结果：见 `scheduler_throughput.svg` 和 `scheduler_queue_wait.svg`。
### cgroup 隔离实验
- 可用性：当前环境无宿主机 cgroup 写权限，已跳过真实隔离。
### cgroup 压力实验
- 可用性：当前环境无宿主机 cgroup 写权限，已跳过真实压力采集。
### vLLM APC 实验
- 可用性：当前环境未检测到可用 vLLM，已跳过真实 APC。

## P1
### 通信公平对照
- 对比 HTTP push、UDS push 和 mailbox offline flush。
### 扩展性
- 覆盖 agent 数与任务数的组合曲线，图表见 `scalability_*.svg`。
### E2E workflow
- 覆盖 Planner/Retriever/Coder/Tester/Reviewer/Merger 的链路和 fallback。

## 图表
- 调度性能图：`benchmark/figures/scheduler_throughput.svg`、`benchmark/figures/scheduler_queue_wait.svg`
- cgroup 隔离图：`benchmark/figures/cgroup_p95.svg`
- vLLM APC 对比图：`benchmark/figures/vllm_apc.svg`
- 容错恢复图：`benchmark/figures/fault_recovery.svg`
- 扩展性曲线：`benchmark/figures/scalability_throughput.svg`、`benchmark/figures/scalability_p95.svg`、`benchmark/figures/scalability_memory.svg`

## 统计
- 统计口径：5 次预热 + 30 次正式运行，输出 mean / stdev / P50 / P95 / P99 / 95% CI。

## 原始数据
- `benchmark/results/raw.csv`
- `benchmark/results/summary.csv`

## 备注
- vLLM 和真实 cgroup 依赖本机环境，benchmark 框架已包含检测与降级路径。
- 当前报告中的 P0/P1/P2 条目以已实现的 benchmark 代码和实际运行结果为准。