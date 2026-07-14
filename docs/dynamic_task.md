# 动态任务

Runtime 支持运行中由 Agent 创建子任务，不要求开发者预定义完整图。

API：
- `POST /tasks/{task_id}/spawn`
- `GET /tasks/{task_id}/children`
- `GET /tasks/{task_id}/dag`
- `POST /tasks/{task_id}/dependencies`

行为：
- 校验父任务存在。
- 子任务继承父任务 `trace_id`。
- `inherit_context=true` 时继承 `context_id`。
- 写入 `parent_task_id` 和父任务 `children`。
- 依赖未满足时停留等待，依赖完成后进入 READY。

源码依据：`aruntime/daemon/main.py`, `aruntime/scheduler/kernel.py`。

测试依据：`testing/unittest/daemon/test_lifecycle.py::test_spawn_task_api_returns_children_and_dag`。
