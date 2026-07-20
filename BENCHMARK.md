# Agent Runtime Benchmark

## 结论
- 当前阶段只保留三组真实性能实验：调度策略、上下文优化、容错策略。
- 每组执行 5 次预热和 30 次正式运行，输出 mean、P50、P95、标准差和 95% CI。

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
| 调度策略 | FIFO | 30 | 317.454 | 75.851 | 304.563 | 152.916 | 0.000 | |
| 调度策略 | resource-aware | 30 | 324.252 | 74.237 | 323.845 | 140.113 | 0.000 | |
| 上下文优化 | full-context | 30 | 39.180 | 766.163 | 0.775 | 0.000 | 0.000 | |
| 上下文优化 | reuse+compression | 30 | 20.048 | 1496.631 | 0.719 | 0.000 | 0.000 | |
| 容错策略 | no-recovery | 30 | 3.750 | 8003.390 | 0.053 | 0.000 | 0.000 | |
| 容错策略 | retry | 30 | 3.540 | 8479.452 | 0.045 | 0.000 | 0.000 | |
| 容错策略 | fallback | 30 | 4.393 | 6832.290 | 0.076 | 0.000 | 1.000 | |

## 三组实验
- 调度策略：FIFO vs resource-aware，保持相同任务数、Agent 数、执行时间、CPU/Memory 请求和并发上限。
- 上下文优化：完整上下文重复发送 vs context reuse + structured compression，并验证关键约束保留。
- 容错策略：无自动恢复、retry、fallback。

## 图表
- 调度性能图：`benchmark/figures/scheduler_throughput.svg`、`benchmark/figures/scheduler_queue_wait.svg`
- 容错恢复图：`benchmark/figures/fault_recovery.svg`

## 统计
- 统计口径：5 次预热 + 30 次正式运行，输出 mean / stdev / P50 / P95 / P99 / 95% CI。

## 原始数据
- `benchmark/results/raw.csv`
- `benchmark/results/summary.csv`

## 备注
- 真实 vLLM KV Cache 和真实 cgroup 不作为当前提交阻塞项。
# Benchmark Classification

本仓库 benchmark 分三类：

- Synthetic Smoke：使用 `--smoke`，输出 `data_kind=synthetic_smoke` 和 `performance_claim_allowed=false`，只验证框架。
- Deterministic Microbenchmark：`testing/perf/suite.py` 中的本地确定性调度、上下文、容错、cgroup 指标。
- Real Agent Macrobenchmark：`testing/perf/comparison/runner.py` 中 DirectExecutionProvider 与 AgentRuntimeExecutionProvider 的真实对比。

真实性能结论只能来自 `performance_claim_allowed=true` 的报告。
