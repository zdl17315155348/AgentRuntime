# 实验规范

每个实验固定记录：实验目的、对照组、实验组、输入规模、重复次数、平均值、P95、结论、局限性。

指标：
- `task_throughput`
- `avg_queue_wait_ms`
- `p95_queue_wait_ms`
- `agent_runtime_ms`
- `llm_latency_ms`
- `token_saving_ratio`
- `context_hit_ratio`
- `failure_recovery_time_ms`
- `ipc_delivery_latency_ms`

执行入口：`scripts/benchmark_docker_openeuler.sh`。
