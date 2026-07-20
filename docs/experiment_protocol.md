# Experiment Protocol

## 数据类别

- `synthetic_smoke`：只验证 benchmark 框架，不允许形成性能结论。
- `real_agent`：使用 DirectExecutionProvider 和 AgentRuntimeExecutionProvider，允许进入性能分析。

## 运行顺序

先通过：

```bash
python3 scripts/final_acceptance.py
```

正式真实实验前必须通过：

```bash
python3 scripts/final_acceptance.py --require-real
```

## Benchmark

Smoke：

```bash
make benchmark-smoke
```

真实小样本：

```bash
make benchmark-real-small
```

输出目录：

```text
run-data/benchmarks/<benchmark_id>/
```

核心文件：

```text
raw_runs.csv
workflow_runs.csv
trial_runs.csv
paired_runs.csv
summary.csv
report.json
```

`report.json.performance_claim_allowed=false` 的结果不得用于答辩性能结论。
