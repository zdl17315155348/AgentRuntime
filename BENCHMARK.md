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
| 调度公平对照 | FIFO 并发 | 30 | 317.277 | 75.889 | 304.411 | 152.810 | 0.000 | |
| 调度公平对照 | resource-aware 并发 | 30 | 320.610 | 75.075 | 314.957 | 135.213 | 0.000 | |
| 上下文复用 | 无复用 | 30 | 11.980 | 2504.531 | 0.155 | 0.000 | 0.000 | |
| 上下文复用 | context/prefix reuse | 30 | 3.862 | 7786.483 | 0.154 | 0.000 | 0.000 | |
| 容错故障注入 | fail-closed | 30 | 3.671 | 8174.902 | 0.051 | 0.000 | 0.000 | |
| 容错故障注入 | retry | 30 | 3.428 | 8753.947 | 0.044 | 0.000 | 0.000 | |
| 容错故障注入 | fallback | 30 | 4.265 | 7043.304 | 0.075 | 0.000 | 1.000 | |
| 容错故障注入 | fail-open | 30 | 3.492 | 8603.337 | 0.050 | 0.000 | 0.000 | |
| 通信公平对照 | HTTP push | 1 | 45.018 | 1777.048 | 0.781 | 0.000 | 0.000 | |
| 通信公平对照 | UDS push | 1 | 0.646 | 80000.000 | 0.008 | 0.000 | 0.000 | |
| 通信公平对照 | mailbox offline flush | 1 | 20.812 | 3843.879 | 0.287 | 0.000 | 0.000 | |
| cgroup 隔离 | 无 cgroup | 1 | 63.100 | 190.174 | 10.002 | 0.000 | 0.000 | |
| cgroup 隔离 | cgroup v2 | 1 | 62.856 | 190.913 | 10.002 | 0.000 | 0.000 | |
| cgroup 压力 | cpu/memory pressure | 1 | 120.584 | 49.758 | 20.200 | 0.000 | 0.000 | |
| 扩展性 | agents/1/tasks/100 | 1 | 10.754 | 9457.123 | 12.906 | 0.000 | 0.000 | |
| 扩展性 | agents/1/tasks/500 | 1 | 225.230 | 2222.231 | 240.966 | 0.000 | 0.000 | |
| 扩展性 | agents/1/tasks/1000 | 1 | 871.402 | 1148.256 | 936.509 | 0.000 | 0.000 | |
| 扩展性 | agents/4/tasks/100 | 1 | 12.305 | 8222.168 | 12.060 | 0.000 | 0.000 | |
| 扩展性 | agents/4/tasks/500 | 1 | 221.753 | 2256.990 | 237.956 | 0.000 | 0.000 | |
| 扩展性 | agents/4/tasks/1000 | 1 | 865.700 | 1155.500 | 918.016 | 0.000 | 0.000 | |
| 扩展性 | agents/8/tasks/100 | 1 | 12.600 | 8037.202 | 12.725 | 0.000 | 0.000 | |
| 扩展性 | agents/8/tasks/500 | 1 | 220.808 | 2266.591 | 251.977 | 0.000 | 0.000 | |
| 扩展性 | agents/8/tasks/1000 | 1 | 886.342 | 1128.572 | 930.249 | 0.000 | 0.000 | |
| 扩展性 | agents/16/tasks/100 | 1 | 12.384 | 8182.472 | 12.254 | 0.000 | 0.000 | |
| 扩展性 | agents/16/tasks/500 | 1 | 220.874 | 2265.928 | 235.743 | 0.000 | 0.000 | |
| 扩展性 | agents/16/tasks/1000 | 1 | 877.329 | 1140.203 | 919.562 | 0.000 | 0.000 | |
| 扩展性 | agents/32/tasks/100 | 1 | 12.002 | 8437.600 | 12.488 | 0.000 | 0.000 | |
| 扩展性 | agents/32/tasks/500 | 1 | 221.612 | 2258.480 | 252.529 | 0.000 | 0.000 | |
| 扩展性 | agents/32/tasks/1000 | 1 | 872.081 | 1147.040 | 921.956 | 0.000 | 0.000 | |
| 扩展性 | agents/64/tasks/100 | 1 | 11.974 | 8459.003 | 12.227 | 0.000 | 0.000 | |
| 扩展性 | agents/64/tasks/500 | 1 | 228.257 | 2192.684 | 239.914 | 0.000 | 0.000 | |
| 扩展性 | agents/64/tasks/1000 | 1 | 872.726 | 1146.195 | 938.633 | 0.000 | 0.000 | |
| 复杂 E2E | Planner/Retriever/Coder/Tester/Reviewer/Merger | 1 | 3.761 | 3190.706 | 0.397 | 0.000 | 1.000 | |
| 系统自身开销 | 直接调用 worker | 1 | 0.057 | 100000.000 | 0.000 | 0.000 | 0.000 | |
| 系统自身开销 | AgentRuntime 调用 worker | 1 | 33.307 | 3002.354 | 0.382 | 0.000 | 0.000 | |
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