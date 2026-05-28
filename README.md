# AgentRuntimeOS

面向多智能体的操作系统运行时

## 如何启动
agent-runtime-os/scripts/start_agentd.sh:启动agentd service（后续用systemctl后台运行服务）

agent-runtime-os/scripts/submit.sh:提交agent任务

## 当前进度
agentd接入真实LLM：模型deepseek-v4，能够调用多agent进行对话。

agent生命周期管理：

## 测试
### 单元测试(testing/unittest/)

core/test_lifecycle_core.py:测试Agent生命周期状态。

验证状态转换的合法性（如CREATED->READY->RUNNING->COMPLETED）以及非法转换能否正确拦截


daemon/test_lifecycle.py:测试通过agentd API操作时Agent生命周期是否按预期流转。

验证创建Agent、提交任务后状态变化、重复注册、不存在的Agent等场景。


daemon/test_api.py:测试agentd各API端点的正确性。

验证注册、提交、查询等接口的请求和响应格式是否正确。