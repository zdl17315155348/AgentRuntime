# Limitations

- 当前 Runtime 是单节点实现。
- 通用抢占未实现；已实现 timeout、cancel、kill、lease 回收和 fallback。
- 真实 Agent 结果受 DeepSeek、Codex CLI、网络和 API 限流波动影响。
- Codex 内部 KV Cache 不由 Runtime 直接控制。
- Context token 节省为运行指标估算，口径来自输入/输出 token 与上下文复用记录。
- `synthetic_smoke` benchmark 只能验证框架，不允许作为真实性能结论。
