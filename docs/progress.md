# 进度记录

## 2026-07-14

- 对齐 README 能力和源码实现，新增 `docs/implementation_status.md` 状态表。
- `aruntime/core/models.py` 增加 `AgentCapability`、`required_capability`、`children`、`timeout_ms`、`idempotency_key`、`side_effect_level`、`compensation`。
- `aruntime/core/acb.py` 增加 Agent 生命周期 FSM 和 timeline 强制记录。
- `aruntime/scheduler/kernel.py` 增加 `capability_aware`、`cost_aware`、`reliability_aware`，支持能力匹配和 BLOCKED 资源阻塞。
- `aruntime/daemon/main.py` 增加动态任务 API：`/tasks/{task_id}/spawn`、`/children`、`/dag`、`/dependencies`。
- `aruntime/context/manager.py` 和 `aruntime/context/types.py` 增加 readonly 版本追加、private 隔离和 rollback diff 测试依据。
- `aruntime/comm/message.py` 和 `aruntime/comm/router.py` 增加 message_id、ACK、去重、未 ACK 重放。
- Demo TODO 暂未执行，按用户要求等待后续设计。
