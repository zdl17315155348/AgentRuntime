# 实现状态

| 模块 | README 声明能力 | 源码实现位置 | 当前状态 | 测试依据 | 备注 |
|---|---|---|---|---|---|
| Core Model | AgentCapability、Task required_capability、状态补充、幂等/副作用 | `aruntime/core/models.py` | 已实现 | `testing/unittest/core/test_models.py`, `testing/unittest/core/test_tcb.py` | Agent/Task 是 Runtime 一等公民 |
| ACB | Agent 生命周期、timeline、ACB 查询 | `aruntime/core/acb.py`, `aruntime/core/lifecycle.py`, `aruntime/daemon/main.py` | 已实现 | `testing/unittest/core/test_acb.py`, `testing/unittest/core/test_agent_fsm.py` | FAILED 到 READY 必须经过 RECOVERING |
| Scheduler | fifo/priority/deadline/fair_share/resource_aware/capability_aware/cost_aware/reliability_aware | `aruntime/scheduler/kernel.py` | 已实现 | `testing/unittest/scheduler/test_kernel.py`, `testing/unittest/scheduler/test_capability_match.py` | 能力匹配会记录 decision reason |
| Dynamic Task | `/spawn`、DAG、依赖、真实 Demo | `aruntime/daemon/main.py`, `aruntime/scheduler/kernel.py`, `examples/production_incident_demo/scripts/run_demo.py` | 已实现 | `testing/unittest/daemon/test_lifecycle.py`, `testing/integration/test_demo.py` | Demo 至少创建 12 个子任务并校验 DAG |
| Context | shared/private/readonly、version、diff、rollback、prefix metrics、compression | `aruntime/context/manager.py`, `aruntime/context/types.py` | 部分实现 | `testing/unittest/context/test_manager.py`, `testing/unittest/context/test_context_permissions.py` | 当前为结构化压缩，非通用 LLM 语义摘要 |
| Resource | resource classes、lease、reclaim、LLM concurrency、cgroup v2、pressure | `aruntime/resource/types.py`, `aruntime/resource/monitor.py`, `aruntime/resource/cgroup.py` | 已实现 | `testing/unittest/resource/test_resources.py` | cgroup 真实控制依赖宿主权限 |
| Timeout/Kill | attempt timeout、cancel、kill、lease reclaim、fallback | `aruntime/daemon/main.py`, `aruntime/resource/cgroup.py`, `aruntime/worker/agent_worker.py` | 已实现基础闭环 | `testing/unittest/worker/test_attempt_cancel.py`, `testing/integration/test_worker_fallback.py`, `testing/integration/test_demo.py` | 通用抢占未实现 |
| Communication | UDS、mailbox、ACK、去重、重放、dead-letter、Worker ACK | `aruntime/comm/message.py`, `aruntime/comm/router.py`, `aruntime/comm/transport.py`, `aruntime/worker/agent_worker.py` | 已实现 | `testing/unittest/comm/test_router.py`, `testing/unittest/comm/test_router_concurrency.py`, `testing/unittest/comm/test_ack_dedup.py`, `testing/unittest/comm/test_worker_messages.py`, `testing/integration/test_demo.py` | Demo 验证消息只处理一次 |
| Persistence | SQLite/WAL、agents/tasks/attempts/leases/mailbox/trace、恢复 | `aruntime/daemon/store.py`, `aruntime/daemon/recovery_service.py` | 已实现 | `testing/unittest/daemon/test_store_recovery.py` | READY/RUNNING 恢复有单元依据 |
| Heartbeat/Fault | worker crash、fallback attempt、daemon recovery | `aruntime/daemon/fault_service.py`, `aruntime/worker/agent_worker.py`, `aruntime/daemon/main.py`, `aruntime/daemon/recovery_service.py` | 已实现基础 E2E | `testing/integration/test_worker_fallback.py`, `testing/integration/test_daemon_restart.py`, `testing/integration/test_demo.py` | Trace 记录 `worker.lost` 与 `task.fallback` |
| Complex Demo | 真实 agentd、Scheduler、Worker、Tool、pytest、Trace | `examples/production_incident_demo/*`, `testing/integration/test_demo.py` | 已实现 | `make test-demo`, `make test-demo-fault` | `final.patch` 来自真实 `git_diff` tool result |
| Benchmark | raw.csv、summary.csv、svg、vLLM APC mock/real | `testing/perf/*`, `scripts/benchmark_docker_openeuler.sh`, `BENCHMARK.md` | 已实现 | `testing/perf/test_benchmark.py` | 真实 APC 需要 `VLLM_BASE_URL` |
| LangGraph 对比 | Runtime vs workflow 定位 | `docs/langgraph_compare.md`, `docs/architecture.md` | 已实现 | 文档依据 | LangGraph 可作为执行后端，不替代 Runtime |
| Preemption | 通用任务抢占 | - | 未实现 | - | 非赛题必要功能 |
| 多节点部署 | 跨节点 Runtime 部署 | - | 未实现 | - | 当前为单节点 Runtime |

比赛要求范围内的核心机制已经完成；通用抢占、生产级多节点部署和 LLM 语义摘要不在当前实现范围内。
