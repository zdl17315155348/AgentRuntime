# 实现状态

| 模块 | README 声明能力 | 源码实现位置 | 当前状态 | 测试依据 | 备注 |
|---|---|---|---|---|---|
| Core Model | AgentCapability、Task required_capability、状态补充、幂等/副作用 | `aruntime/core/models.py` | 已实现 | `testing/unittest/core/test_models.py`, `testing/unittest/core/test_tcb.py` | Agent/Task 是 Runtime 一等公民 |
| ACB | Agent 生命周期、timeline、ACB 查询 | `aruntime/core/acb.py`, `aruntime/core/lifecycle.py`, `aruntime/daemon/main.py` | 已实现 | `testing/unittest/core/test_acb.py`, `testing/unittest/core/test_agent_fsm.py` | FAILED 到 READY 必须经过 RECOVERING |
| Scheduler | fifo/priority/deadline/fair_share/resource_aware/capability_aware/cost_aware/reliability_aware | `aruntime/scheduler/kernel.py` | 已实现 | `testing/unittest/scheduler/test_kernel.py`, `testing/unittest/scheduler/test_capability_match.py` | 能力匹配会记录 decision reason |
| Dynamic Task | spawn、children、dag、dependencies、trace/context 继承 | `aruntime/daemon/main.py`, `aruntime/scheduler/kernel.py` | 已实现 | `testing/unittest/daemon/test_lifecycle.py` | Demo 目录按用户要求暂不做 |
| Context | shared/private/readonly、version、diff、rollback、prefix metrics、compression | `aruntime/context/manager.py`, `aruntime/context/types.py` | 部分实现 | `testing/unittest/context/test_manager.py`, `testing/unittest/context/test_context_permissions.py` | readonly 是版本追加；LLM summary 压缩为规划中 |
| Resource | resource classes、lease、reclaim、LLM concurrency、cgroup v2、pressure | `aruntime/resource/types.py`, `aruntime/resource/monitor.py`, `aruntime/resource/cgroup.py` | 已实现 | `testing/unittest/resource/test_resources.py` | cgroup 真实控制依赖宿主权限 |
| Timeout/Kill | timeout_ms、timeout trace、kill/reclaim/fallback | `aruntime/daemon/main.py`, `aruntime/resource/cgroup.py` | 部分实现 | `testing/unittest/core/test_models.py`, 既有 lifecycle/fault 测试 | preemption 闭环规划中 |
| Communication | UDS、mailbox、dead-letter、ack、dedup、replay | `aruntime/comm/message.py`, `aruntime/comm/router.py`, `aruntime/comm/transport.py` | 部分实现 | `testing/unittest/comm/test_router.py`, `testing/unittest/comm/test_ack_dedup.py`, `testing/unittest/comm/test_transport.py` | ACK/重放已在 router 层实现，worker reconnect E2E 待补 |
| Persistence | SQLite/WAL、agents/tasks/attempts/leases/mailbox/trace、恢复 | `aruntime/daemon/store.py`, `aruntime/daemon/recovery_service.py` | 已实现 | `testing/unittest/daemon/test_store_recovery.py` | READY/RUNNING 恢复有单元依据 |
| Heartbeat/Fault | heartbeat、restart_budget、circuit breaker、fallback attempt | `aruntime/daemon/fault_service.py`, `aruntime/worker/agent_worker.py`, `aruntime/daemon/main.py` | 部分实现 | `testing/unittest/daemon/test_lifecycle.py` | 端到端 worker reconnect 恢复待继续强化 |
| Benchmark | raw.csv、summary.csv、svg、vLLM APC mock/real | `testing/perf/*`, `scripts/benchmark_docker_openeuler.sh`, `BENCHMARK.md` | 已实现 | `testing/perf/test_benchmark.py` | 真实 APC 需要 `VLLM_BASE_URL` |
| LangGraph 对比 | Runtime vs workflow 定位 | `docs/langgraph_compare.md`, `docs/architecture.md` | 已实现 | 文档依据 | LangGraph 可作为执行后端，不替代 Runtime |
