# Fault Tolerance

当前已实现：
- `FailurePolicy`: retry、fallback、degrade、fail_open、fail_closed。
- worker crash 后隔离、资源回收、按策略 retry/fallback。
- SQLite/WAL 恢复 READY/PENDING/RUNNING 任务。
- `idempotency_key`、`side_effect_level`、`compensation` 字段已进入 `TaskSpec`。

部分实现：
- side effect 的 patch transaction/rollback 仍需 executor 层闭环。
- worker reconnect mailbox E2E 仍需集成测试强化。

源码依据：
- `aruntime/core/models.py`
- `aruntime/daemon/main.py`
- `aruntime/daemon/fault_service.py`
- `aruntime/daemon/recovery_service.py`
- `aruntime/daemon/store.py`

测试依据：
- `testing/unittest/daemon/test_store_recovery.py`
- `testing/unittest/daemon/test_lifecycle.py`
