# AgentRuntimeOS

面向多智能体的操作系统级执行时，提供 Agent 调度、受控执行、资源管理、故障恢复、运行证据和 Dashboard 观测能力。

## 项目亮点和创新点

- OS 级多 Agent 运行时：把 Agent 当作可调度、可观测、可恢复的执行单元，统一管理生命周期、任务、Attempt、资源 lease、workspace 和 artifact。
- 异构 Backend 编排：同一条工作流内支持 `native_planner`、`codex_cli`、`direct_tool` 等后端，Planner、Coder、Tester、Reviewer、Repair 可按能力路由。
- 真实故障恢复闭环：支持 worker/backend SIGKILL 注入、heartbeat 检测、资源回收、同 task fallback 到 `coder_b`、recovery context 传递，并保留可核验证据。
- LangGraph + Runtime 双执行模式：应用层负责动态 DAG、Coder 拓扑串行、集成、测试、审查、修复闭环；Runtime 层负责隔离执行、调度和恢复。
- 受控真实执行环境：openEuler Docker、Codex CLI、bubblewrap、attempt 级 `CODEX_HOME`、环境变量密钥注入和路径共享，避免污染 workspace 和泄漏密钥。
- 证据化交付：统一 summary、trace events、replay manifest、Benchmark、Dashboard 数据和 `final_board_check.py`，每个封板项都有具体依据。

## 总体框架结构

- `aruntime/daemon/`：agentd HTTP 服务、任务提交、运行摘要、Dashboard API、故障注入接口。
- `aruntime/scheduler/`：FIFO、DAG、resource-aware 调度策略。
- `aruntime/worker/`：Agent worker 进程、backend 调用、heartbeat、attempt 执行。
- `aruntime/resource/`：资源监控、lease、回收和 cgroup 集成。
- `aruntime/context/`：上下文管理、恢复上下文、只读共享上下文。
- `aruntime/backends/`：Codex、native planner、direct tool 等执行后端抽象。
- `aruntime/workspace/`：attempt worktree、patch artifact、路径安全和集成支持。
- `aruntime/dashboard/`：Demo、Compare、Benchmark 前端页面。
- `applications/incident_repair/`：生产事故修复应用，包含 planner/coder/tester/reviewer/repair/integrate 节点。
- `examples/production_incident_demo/`：目标事故仓库、Agent 配置、正常/故障 demo 脚本。
- `testing/`：单元、集成、smoke、performance、comparison 测试。
- `scripts/`：openEuler Docker 测试、真实 E2E、Fault E2E、Benchmark、最终封板检查脚本。
- `deploy/`：openEuler 镜像和容器入口。
- `final-evidence/`：最终汇报证据目录。
- `run-data/`：运行时产生的 live summary、graph state、events、workspace、artifact。

## 性能数据来源与可靠性

正式汇报使用 `final-evidence/benchmarks/formal_summary.csv` 中的性能数据，原始生成链路为 `scripts/benchmark_docker_openeuler.sh` 在 openEuler Docker 镜像内执行 `python3 -m pytest testing/perf/test_benchmark.py -q`，测试入口调用 `testing/perf/suite.py::run_suite(seed=42)`，输出 `benchmark/results/raw.csv`、`benchmark/results/summary.csv` 和 `BENCHMARK.md`。

可展示数据：

| 实验 | 对比 | 核心数据 | 结论 |
| --- | --- | --- | --- |
| 上下文优化 | `full-context` vs `reuse+compression` | makespan `46.61ms -> 24.16ms`，throughput `643.66 -> 1242.43`，token saving/cache hit `0% -> 96.67%` | makespan 降低 `48.2%`，吞吐提升 `93.0%` |
| 容错策略 | `no-recovery` vs `fallback` | completion/recovery `0% -> 100%`，makespan `3.96ms -> 4.40ms`，worker restart `0.0216ms` | 约 `11.1%` 时间开销换取 `100%` 恢复 |
| 调度策略 | `FIFO` vs `resource-aware` | queue wait `153.08ms -> 140.78ms` | 队列等待降低 `8.0%`，不宣称整体 makespan 加速 |

可靠性依据：每个对比项执行 5 次预热和 30 次正式运行，汇总 mean、stdev、P50、P95、P99、95% CI；`final-evidence/benchmarks/formal_raw.csv` 保留逐次运行记录；`final-evidence/benchmarks/formal_deterministic_microbenchmark.json` 记录 `performance_claim_allowed: true`，理由为 openEuler Docker benchmark suite 的确定性调度、上下文和容错实验。

## 测试框架

所有测试需要在 openEuler Docker 中运行。优先先定位问题，再运行对应的定向测试。

常用入口：

```bash
bash scripts/test_docker_openeuler.sh
```

定向单测示例：

```bash
docker run --rm --init --privileged \
  -v "$PWD:/workspace/agent-runtime-os" \
  -w /workspace/agent-runtime-os \
  agent-runtime-os:openeuler \
  bash -lc 'python3 -m pytest testing/unittest/applications/test_incident_execution_provider.py -q'
```

封板检查：

```bash
python3 scripts/final_acceptance.py
python3 scripts/final_acceptance.py --require-real
python3 scripts/final_board_check.py
```

真实 E2E：

```bash
python3 scripts/run_real_direct.py --require-real
python3 scripts/run_real_runtime.py --require-real
python3 scripts/run_real_runtime_fault.py --require-real
```

Benchmark：

```bash
bash scripts/benchmark_docker_openeuler.sh
```


## 启动方式

准备真实执行环境变量：

```bash
export OPENAI_API_KEY=...
export DEEPSEEK_API_KEY=...
export CODEX_API_KEY="${CODEX_API_KEY:-$OPENAI_API_KEY}"
export LLM_API_KEY="${LLM_API_KEY:-$DEEPSEEK_API_KEY}"
```

`configs/runtime.json` 默认使用 DeepSeek。未设置 `DEEPSEEK_API_KEY/LLM_API_KEY` 时，`scripts/start_agentd_docker.sh` 会直接退出，避免运行中出现 `Illegal header value b'Bearer '`。

推荐使用 openEuler Docker 启动。该脚本默认使用已有 `agent-runtime-os:openeuler` 镜像、删除旧 `agentd-openeuler` 容器并启动容器内 agentd，不需要也不能提前运行本地 agentd：

```bash
bash scripts/start_agentd_docker.sh
```

该脚本默认会在启动前和退出时清理 `run-data/live/run_*`，避免 Dashboard 自动恢复旧 run。需要保留 run 证据时关闭清理：

```bash
CLEAN_RUNS_ON_START=0 CLEAN_RUNS_ON_EXIT=0 bash scripts/start_agentd_docker.sh
```

首次启动或代码变更后需要重建镜像：

```bash
REBUILD_DOCKER_IMAGE=1 bash scripts/start_agentd_docker.sh
```

启动成功标志：

```text
Uvicorn running on http://0.0.0.0:8234
```

如果已先运行本地 agentd，会占用 `8234`，导致 Docker 报 `address already in use`。先停止本地 agentd，或换端口启动：

```bash
HOST_PORT=8235 bash scripts/start_agentd_docker.sh
```

本地 agentd 只用于非 Docker 调试：

```bash
python3 -m aruntime.daemon.main
```

Dashboard：

```text
http://127.0.0.1:8234/dashboard/demo.html
http://127.0.0.1:8234/dashboard/compare.html
http://127.0.0.1:8234/dashboard/benchmarks.html
```

运行结果：

```text
http://127.0.0.1:8234/runs/<run_id>/summary
http://127.0.0.1:8234/runs/<run_id>/events?after_id=0
http://127.0.0.1:8234/demo/runs/<run_id>/stream
```

demo：

- `bash examples/production_incident_demo/scripts/run_normal.sh`
  运行生产事故修复正常流程，验证 Planner、Coder、Tester、Reviewer、Integrate 的完整闭环。
- `bash examples/production_incident_demo/scripts/run_fault.sh`
  运行故障注入流程，验证 worker/backend 失败后的资源回收、fallback、恢复上下文和最终修复结果。
