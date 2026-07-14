# Scheduler

当前策略：`fifo`、`priority`、`deadline`、`fair_share`、`resource_aware`、`capability_aware`、`cost_aware`、`reliability_aware`。

能力调度流程：
1. READY 任务进入 `KernelScheduler.dispatch_ready`。
2. 读取 `TaskSpec.required_capability`。
3. 用 `_match_capability` 筛选 `AgentSpec.capability`。
4. 按 reliability、cost、priority、deadline、resource 继续排序。
5. 写入 `task.scheduler_decision_reason`。

源码依据：`aruntime/scheduler/kernel.py`。

测试依据：
- `testing/unittest/scheduler/test_kernel.py`
- `testing/unittest/scheduler/test_capability_match.py`
