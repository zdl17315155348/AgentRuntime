#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

source "$PROJECT_DIR/scripts/docker_common.sh"

IMAGE_TAG="${IMAGE_TAG:-agent-runtime-os:openeuler}"
HOST_PORT="${HOST_PORT:-8234}"
CONTAINER_NAME="${CONTAINER_NAME:-agentd-openeuler}"
CONFIG_PATH="${CONFIG_PATH:-$PROJECT_DIR/configs/runtime.json}"
RUN_DATA_DIR="${RUN_DATA_DIR:-$PROJECT_DIR/.runtime-docker}"
ARTIFACT_DIR="${ARTIFACT_DIR:-$RUN_DATA_DIR/artifacts}"
WORKSPACE_DIR="${WORKSPACE_DIR:-$RUN_DATA_DIR/workspaces}"
STATE_DIR="${STATE_DIR:-$RUN_DATA_DIR/state}"
LOG_DIR="${LOG_DIR:-$RUN_DATA_DIR/logs}"

ensure_docker_available

if [ ! -f "$CONFIG_PATH" ]; then
  echo "未找到配置文件: $CONFIG_PATH"
  exit 1
fi

if [ ! -x "$PROJECT_DIR/third_party/codex/codex" ]; then
  echo "未找到 Codex 二进制: $PROJECT_DIR/third_party/codex/codex"
  exit 1
fi

mkdir -p "$ARTIFACT_DIR" "$WORKSPACE_DIR" "$STATE_DIR" "$LOG_DIR"

$DOCKER build \
  -f deploy/Dockerfile.openeuler \
  -t "$IMAGE_TAG" \
  .

$DOCKER rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

RUN_ARGS=(
  --rm
  --name "$CONTAINER_NAME"
  -p "${HOST_PORT}:8234"
  -v "$CONFIG_PATH:/app/configs/runtime.json:ro"
  -v "$WORKSPACE_DIR:/runtime/workspaces"
  -v "$ARTIFACT_DIR:/runtime/artifacts"
  -v "$STATE_DIR:/runtime/state"
  -v "$LOG_DIR:/runtime/logs"
  -e RUNTIME_CONFIG=/app/configs/runtime.json
)

for key in DEEPSEEK_API_KEY LLM_API_KEY OPENAI_API_KEY CODEX_API_KEY AGENTD_ENABLE_FAULT_INJECTION; do
  if [ -n "${!key:-}" ]; then
    RUN_ARGS+=(-e "$key")
  fi
done

$DOCKER run \
  "${RUN_ARGS[@]}" \
  "$IMAGE_TAG"
