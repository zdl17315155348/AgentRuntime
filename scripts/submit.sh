#!/bin/bash
# 提交工作流任务
# 用法：./scripts/submit.sh [workflow_file]

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# 默认工作流文件
WORKFLOW_FILE="${1:-examples/code_repair/workflow.yaml}"

echo "▶ 提交工作流: $WORKFLOW_FILE"
python3 -m aruntime.cli.main submit "$WORKFLOW_FILE"