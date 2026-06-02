#!/bin/bash
# 运行集成测试（需要启动 agentd）
# 用法：./scripts/test_integration.sh

set -e

cd "$(cd "$(dirname "$0")/.." && pwd)"

cleanup() {
  if [[ -n "${AGENTD_PID:-}" ]]; then
    echo ""
    echo "  停止 agentd..."
    kill "$AGENTD_PID" 2>/dev/null || true
    wait "$AGENTD_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

echo "=========================================="
echo "  集成测试（需要启动 agentd）"
echo "=========================================="

# 清理缓存
rm -rf .pytest_cache
find testing/ -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# ───── 杀掉旧的 agentd 进程 ─────
echo "  检查并清理旧 agentd 进程..."
# 方式一：fuser（通常预装）
fuser -k 8234/tcp 2>/dev/null || true
# 方式二：pkill（按进程名）
pkill -f "aruntime.daemon.main" 2>/dev/null || true
sleep 1

# ───── 启动新的 agentd ─────
echo "  启动 agentd..."
if [[ "${USE_REAL_LLM:-0}" == "1" ]]; then
  python3 -m aruntime.daemon.main &
else
  LLM_BACKEND=mock LLM_API_KEY="" python3 -m aruntime.daemon.main &
fi
AGENTD_PID=$!
sleep 2

# ───── 运行测试 ─────
echo ""
python3 -m pytest testing/unittest/daemon/ -v

echo ""
echo "✅ 集成测试完成"
