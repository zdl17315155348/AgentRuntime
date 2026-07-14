# Agent / Task 抽象

Agent 是可调度、可隔离、可恢复的系统实体，不是普通函数节点。

源码依据：
- `aruntime/core/models.py`: `AgentSpec`, `AgentCapability`, `TaskSpec`, `TaskStatus`, `AgentStatus`
- `aruntime/core/acb.py`: `AgentControlBlock`
- `aruntime/scheduler/kernel.py`: capability matching

测试依据：
- `testing/unittest/core/test_models.py`
- `testing/unittest/core/test_agent_fsm.py`
- `testing/unittest/scheduler/test_capability_match.py`
