# Context

Context 当前包含：
- `shared`: 授权 Agent 共享读写。
- `private`: 仅 owner agent 可读写。
- `readonly`: 不能原地覆盖，更新生成新版本。
- `context_diff`: 记录最近一次更新或 rollback。
- `prefix_hash`、`prefix_block_id`、`cache_hit`、`saved_tokens`: 逻辑 prefix reuse 指标。

源码依据：`aruntime/context/manager.py`, `aruntime/context/types.py`。

测试依据：
- `testing/unittest/context/test_manager.py`
- `testing/unittest/context/test_context_permissions.py`

真实 KV Cache 说明：Runtime 层当前实现逻辑 prefix reuse 抽象；真实后端 APC 实验通过 benchmark 的 vLLM 配置验证。
