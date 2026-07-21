#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

source "$PROJECT_DIR/scripts/docker_common.sh"

IMAGE_TAG="${IMAGE_TAG:-agent-runtime-os:openeuler}"
ensure_docker_available

: "${OPENAI_API_KEY:?OPENAI_API_KEY is required}"
if [ -z "${DEEPSEEK_API_KEY:-}" ] && [ -z "${LLM_API_KEY:-}" ]; then
  echo "DEEPSEEK_API_KEY or LLM_API_KEY is required" >&2
  exit 1
fi

CODEX_HOME_MOUNT=()
if [ -f "${CODEX_HOME:-$HOME/.codex}/config.toml" ]; then
  CODEX_HOME_MOUNT=(-v "${CODEX_HOME:-$HOME/.codex}/config.toml:/root/.codex/config.toml:ro")
fi

$DOCKER build \
  -f deploy/Dockerfile.openeuler \
  -t "$IMAGE_TAG" \
  .
$DOCKER run --rm \
  --privileged \
  "${CODEX_HOME_MOUNT[@]}" \
  -e "OPENAI_API_KEY=$OPENAI_API_KEY" \
  -e "CODEX_API_KEY=${CODEX_API_KEY:-$OPENAI_API_KEY}" \
  -e "DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-${LLM_API_KEY:-}}" \
  -e "LLM_API_KEY=${LLM_API_KEY:-${DEEPSEEK_API_KEY:-}}" \
  -e "http_proxy=${http_proxy:-}" \
  -e "https_proxy=${https_proxy:-}" \
  -e "all_proxy=${all_proxy:-}" \
  -e "HTTP_PROXY=${HTTP_PROXY:-}" \
  -e "HTTPS_PROXY=${HTTPS_PROXY:-}" \
  -e "ALL_PROXY=${ALL_PROXY:-}" \
  -e "LLM_BACKEND=deepseek" \
  -e "AGENTD_ENABLE_FAULT_INJECTION=true" \
  "$IMAGE_TAG" bash -lc '
set -euo pipefail
export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost
bash examples/production_incident_demo/scripts/run_real.sh
'
