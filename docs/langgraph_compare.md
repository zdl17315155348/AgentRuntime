# LangGraph 对比

LangGraph 解决应用层图编排问题；AgentRuntimeOS 解决系统层执行管理问题。

| 维度 | LangGraph | AgentRuntimeOS |
|---|---|---|
| 定位 | 应用层 workflow / graph | 系统层 Agent Runtime |
| 核心对象 | Graph, Node, Edge, State | Agent, Task, ACB, Context, Resource, Message, Scheduler |
| 图结构 | 通常预定义 | 可运行中 spawn 子任务并扩展 DAG |
| 调度 | 应用逻辑驱动 | priority/deadline/fair_share/resource/capability 策略 |
| 资源隔离 | 非核心职责 | ResourceLease、LLM 并发、cgroup v2 |
| 容错 | 节点逻辑自行处理 | retry/fallback/degrade/recovery 由 Runtime 管理 |
| 通信 | 图状态传递 | UDS、mailbox、ACK、重放、dead-letter |
| 持久化恢复 | 依赖应用/后端配置 | SQLite/WAL 恢复 tasks/leases/mailbox/trace |

分层关系：LangGraph 可以作为某个 Agent 的执行后端；AgentRuntimeOS 负责统一调度、资源隔离、上下文管理、通信和容错。

案例：Architect Agent 负责规划并 spawn 子任务；Codex Agent 匹配 `can_code=true, language=python`；Cursor/Edit Agent 做跨文件修改；Tester Agent 匹配 `can_test=true`。Runtime 根据 `required_capability` 和资源状态选择 Agent。
