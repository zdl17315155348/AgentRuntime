#!/bin/bash
# 启动 agentd 守护进程
# 用法：./scripts/start_agentd.sh [mock|deepseek]

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if [ "$1" == "mock" ]; then
    export LLM_BACKEND=mock
    echo "▶ 启动 agentd（Mock 模式）"
elif [ "$1" == "deepseek" ]; then
    export LLM_BACKEND=deepseek
    echo "▶ 启动 agentd（DeepSeek 模式）"
else
    echo "▶ 启动 agentd（从 configs/runtime.json 读取配置）"
fi

python3 -m aruntime.daemon.main