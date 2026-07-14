# 架构

```text
API / CLI
  |
agentd
  |-- Scheduler: Task queue, DAG, capability/resource policy
  |-- ACB: Agent lifecycle, status timeline, current task
  |-- Context: shared/private/readonly, compression, prefix metrics
  |-- Resource: lease, reclaim, cgroup v2, LLM concurrency
  |-- Communication: UDS, mailbox, ack, replay, dead-letter
  |-- Persistence: SQLite/WAL, recovery
  |-- Observability: trace, metrics, benchmark outputs
  |
Worker processes
```

核心对象：Agent、Task、ACB、Context、Resource、Message、Scheduler。

源码入口：`aruntime/daemon/main.py`。
