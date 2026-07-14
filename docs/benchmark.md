# Benchmark

Benchmark 入口：`bash scripts/benchmark_docker_openeuler.sh`。

输出：
- `benchmark/results/raw.csv`
- `benchmark/results/summary.csv`
- `benchmark/figures/*.svg`

实验覆盖：
- Scheduler: FIFO vs priority/resource_aware/fair_share。
- Context: no reuse vs reuse/compression/prefix cache。
- Fault tolerance: retry/fallback/degrade。
- IPC: HTTP polling、UDS push、mailbox replay。
- Scalability: 1/4/8/16/32 Agent 并发吞吐。

真实 vLLM APC 需要 `VLLM_BASE_URL`；无 vLLM 时运行 mock 实验并在结果中标记。

源码依据：`testing/perf/*`, `scripts/benchmark_docker_openeuler.sh`, `BENCHMARK.md`。
