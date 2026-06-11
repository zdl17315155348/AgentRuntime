#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

source "$PROJECT_DIR/scripts/docker_common.sh"

IMAGE_TAG="${IMAGE_TAG:-agent-runtime-os:openeuler}"
HOST_PORT="${HOST_PORT:-8234}"
CONTAINER_NAME="${CONTAINER_NAME:-agentd-openeuler}"
CONFIG_PATH="${CONFIG_PATH:-$PROJECT_DIR/configs/runtime.json}"

ensure_docker_available

if [ ! -f "$CONFIG_PATH" ]; then
  echo "未找到配置文件: $CONFIG_PATH"
  exit 1
fi

$DOCKER build -t "$IMAGE_TAG" .

$DOCKER rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

$DOCKER run --rm \
  --name "$CONTAINER_NAME" \
  -p "${HOST_PORT}:8234" \
  -v "$CONFIG_PATH:/app/configs/runtime.json:ro" \
  -e RUNTIME_CONFIG=/app/configs/runtime.json \
  "$IMAGE_TAG"
