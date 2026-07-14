# Agent 生命周期

状态迁移由 ACB 强制执行。

| 当前状态 | 允许目标 |
|---|---|
| CREATED | READY, FAILED |
| READY | RUNNING, SUSPENDED, KILLED |
| RUNNING | WAITING, COMPLETED, FAILED, ISOLATED, KILLED |
| WAITING | READY, FAILED, KILLED |
| FAILED | RECOVERING, ISOLATED, KILLED |
| RECOVERING | READY, KILLED |
| ISOLATED | READY, KILLED |
| SUSPENDED | READY, KILLED |
| COMPLETED | 终态 |
| KILLED | 终态 |

源码依据：`aruntime/core/acb.py`, `aruntime/core/lifecycle.py`。

测试依据：`testing/unittest/core/test_agent_fsm.py`。
