#!/bin/bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
PROJECT_DIR="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
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
SHARED_RUN_DATA_DIR="${SHARED_RUN_DATA_DIR:-$PROJECT_DIR/run-data}"
CLEAN_RUNS_ON_START="${CLEAN_RUNS_ON_START:-1}"
CLEAN_RUNS_ON_EXIT="${CLEAN_RUNS_ON_EXIT:-1}"
CLEAN_RUNTIME_ON_START="${CLEAN_RUNTIME_ON_START:-$CLEAN_RUNS_ON_START}"
CLEAN_RUNTIME_ON_EXIT="${CLEAN_RUNTIME_ON_EXIT:-$CLEAN_RUNS_ON_EXIT}"
CODEX_HOME_MOUNT=()
if [ -f "${CODEX_HOME:-$HOME/.codex}/config.toml" ]; then
  CODEX_HOME_MOUNT=(-v "${CODEX_HOME:-$HOME/.codex}/config.toml:/root/.codex/config.toml:ro")
fi

cleanup_image() {
  if $DOCKER image inspect "$IMAGE_TAG" >/dev/null 2>&1; then
    printf '%s\n' "$IMAGE_TAG"
    return 0
  fi
  if $DOCKER image inspect "openeuler/openeuler:24.03-lts" >/dev/null 2>&1; then
    printf '%s\n' "openeuler/openeuler:24.03-lts"
    return 0
  fi
  return 1
}

clean_live_runs() {
  local reason="$1"
  local live_dir="$SHARED_RUN_DATA_DIR/live"
  if [ ! -d "$live_dir" ]; then
    return
  fi
  echo "清理 ${reason} demo run: $live_dir/run_*"
  if ! find "$live_dir" -mindepth 1 -maxdepth 1 -type d -name 'run_*' -exec rm -rf {} + 2>/dev/null; then
    echo "宿主清理权限不足，改用 Docker 清理 root-owned demo run"
    local image
    if image="$(cleanup_image)"; then
      $DOCKER run --rm --privileged -v "$live_dir:/cleanup-live" "$image" bash -lc "find /cleanup-live -mindepth 1 -maxdepth 1 -type d -name 'run_*' -exec rm -rf {} +"
    else
      echo "缺少可用清理镜像，无法清理 root-owned demo run"
      return 1
    fi
  fi
}

clean_runtime_state() {
  local reason="$1"
  echo "清理 ${reason} agentd runtime state: $STATE_DIR/state.db*"
  if [ -d "$STATE_DIR" ]; then
    if ! find "$STATE_DIR" -maxdepth 1 -type f \( -name 'state.db' -o -name 'state.db-wal' -o -name 'state.db-shm' \) -exec rm -f {} + 2>/dev/null; then
      echo "宿主清理权限不足，改用 Docker 清理 root-owned agentd state"
      local image
      if image="$(cleanup_image)"; then
        $DOCKER run --rm --privileged -v "$STATE_DIR:/cleanup-state" "$image" bash -lc "rm -f /cleanup-state/state.db /cleanup-state/state.db-wal /cleanup-state/state.db-shm"
      else
        echo "缺少可用清理镜像，无法清理 root-owned agentd state"
        return 1
      fi
    fi
  fi

  for runtime_dir in "$WORKSPACE_DIR" "$ARTIFACT_DIR"; do
    if [ ! -d "$runtime_dir" ]; then
      continue
    fi
    echo "清理 ${reason} agentd runtime 目录: $runtime_dir/{run_*,task_*}"
    if ! find "$runtime_dir" -mindepth 1 -maxdepth 1 -type d \( -name 'run_*' -o -name 'task_*' \) -exec rm -rf {} + 2>/dev/null; then
      echo "宿主清理权限不足，改用 Docker 清理 root-owned runtime 目录"
      local image
      if image="$(cleanup_image)"; then
        $DOCKER run --rm --privileged -v "$runtime_dir:/cleanup-runtime" "$image" bash -lc "find /cleanup-runtime -mindepth 1 -maxdepth 1 -type d \( -name 'run_*' -o -name 'task_*' \) -exec rm -rf {} +"
      else
        echo "缺少可用清理镜像，无法清理 root-owned runtime 目录"
        return 1
      fi
    fi
  done
}

if [ "${AGENTD_START_AGENTD_DOCKER_SOURCE_ONLY:-0}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

cleanup_on_exit() {
  local status=$?
  if [ "$CLEAN_RUNS_ON_EXIT" = "1" ]; then
    clean_live_runs "退出时"
  fi
  if [ "$CLEAN_RUNTIME_ON_EXIT" = "1" ]; then
    clean_runtime_state "退出时"
  fi
  exit "$status"
}

trap cleanup_on_exit EXIT

ensure_docker_available

if [ ! -f "$CONFIG_PATH" ]; then
  echo "未找到配置文件: $CONFIG_PATH"
  exit 1
fi

if [ ! -x "$PROJECT_DIR/third_party/codex/codex" ]; then
  echo "未找到 Codex 二进制: $PROJECT_DIR/third_party/codex/codex"
  exit 1
fi

CONFIG_BACKEND="$(python3 -c 'import json,sys; print((json.load(open(sys.argv[1])).get("llm") or {}).get("backend",""))' "$CONFIG_PATH")"
if [ "$CONFIG_BACKEND" = "deepseek" ] && [ -z "${LLM_API_KEY:-${DEEPSEEK_API_KEY:-}}" ]; then
  echo "缺少 DeepSeek Key：请先 export DEEPSEEK_API_KEY 或 LLM_API_KEY"
  echo "示例：export LLM_API_KEY=\"\$DEEPSEEK_API_KEY\""
  exit 1
fi

mkdir -p "$ARTIFACT_DIR" "$WORKSPACE_DIR" "$STATE_DIR" "$LOG_DIR" "$SHARED_RUN_DATA_DIR"

$DOCKER rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

if [ "$CLEAN_RUNS_ON_START" = "1" ]; then
  clean_live_runs "启动前旧"
fi

if [ "$CLEAN_RUNTIME_ON_START" = "1" ]; then
  clean_runtime_state "启动前旧"
fi

if [ "${REBUILD_DOCKER_IMAGE:-0}" = "1" ]; then
  $DOCKER build \
    -f deploy/Dockerfile.openeuler \
    -t "$IMAGE_TAG" \
    .
else
  if ! $DOCKER image inspect "$IMAGE_TAG" >/dev/null 2>&1; then
    echo "镜像不存在，请先运行: REBUILD_DOCKER_IMAGE=1 bash scripts/start_agentd_docker.sh"
    exit 1
  fi
  echo "跳过 Docker 构建，使用已有镜像: $IMAGE_TAG"
fi

RUN_ARGS=(
  --rm
  --init
  --privileged
  --name "$CONTAINER_NAME"
  -p "${HOST_PORT}:8234"
  -v "$CONFIG_PATH:/app/configs/runtime.json:ro"
  -v "$WORKSPACE_DIR:/runtime/workspaces"
  -v "$ARTIFACT_DIR:/runtime/artifacts"
  -v "$STATE_DIR:/runtime/state"
  -v "$LOG_DIR:/runtime/logs"
  -v "$SHARED_RUN_DATA_DIR:/app/run-data"
  -v "$PROJECT_DIR/aruntime/dashboard:/app/aruntime/dashboard:ro"
  -e RUNTIME_CONFIG=/app/configs/runtime.json
)

for key in DEEPSEEK_API_KEY LLM_API_KEY OPENAI_API_KEY CODEX_API_KEY AGENTD_ENABLE_FAULT_INJECTION; do
  if [ -n "${!key:-}" ]; then
    RUN_ARGS+=(-e "$key")
  fi
done

$DOCKER run \
  "${CODEX_HOME_MOUNT[@]}" \
  "${RUN_ARGS[@]}" \
  "$IMAGE_TAG"
