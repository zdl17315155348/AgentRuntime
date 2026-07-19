# Agent Runtime Benchmark

## 结论
- 当前阶段只保留三组真实性能实验：调度策略、上下文优化、容错策略。
- 每组执行 5 次预热和 30 次正式运行，输出 mean、P50、P95、标准差和 95% CI。

## 复现方法
1. 运行 `bash scripts/benchmark_docker_openeuler.sh`。
2. 脚本会在 openEuler Docker 中执行 `pytest testing/perf/test_benchmark.py -q`。
3. 结果会落到 `benchmark/results/raw.csv`、`benchmark/results/summary.csv`、`benchmark/figures/*.svg` 和根目录 `BENCHMARK.md`。

## 实验环境
- Python：`3.11.6`
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
| 调度策略 | FIFO | 30 | 318.409 | 75.637 | 305.357 | 153.333 | 0.000 | |
| 调度策略 | resource-aware | 30 | 325.872 | 73.863 | 325.280 | 140.376 | 0.000 | |
| 上下文优化 | full-context | 30 | 46.672 | 642.810 | 0.914 | 0.000 | 0.000 | |
| 上下文优化 | reuse+compression | 30 | 23.776 | 1261.829 | 0.832 | 0.000 | 0.000 | |
| 容错策略 | no-recovery | 30 | 3.877 | 7740.526 | 0.054 | 0.000 | 0.000 | |
| 容错策略 | retry | 30 | 3.569 | 8407.040 | 0.043 | 0.000 | 0.000 | |
| 容错策略 | fallback | 30 | 4.338 | 6916.837 | 0.072 | 0.000 | 1.000 | |

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