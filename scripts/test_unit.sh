#!/bin/bash
# 运行单元测试（不依赖 agentd）
# 用法：./scripts/test_unit.sh

set -e

cd "$(cd "$(dirname "$0")/.." && pwd)"

echo "=========================================="
echo "  单元测试（不依赖 agentd）"
echo "=========================================="

# 清理缓存
rm -rf .pytest_cache
find testing/ -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# 运行单元测试
python3 -m pytest testing/unittest/core/ testing/unittest/scheduler/ testing/unittest/context/ testing/unittest/api/ testing/unittest/comm/ testing/unittest/llm/ testing/unittest/resource/ testing/unittest/observability/ testing/unittest/applications/ -v

echo ""
echo "✅ 单元测试完成"
