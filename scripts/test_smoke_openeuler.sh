#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

IMAGE_TAG="${IMAGE_TAG:-agent-runtime-os:openeuler}"
BASE_IMAGE="${BASE_IMAGE:-openeuler-24.03-lts:latest}"
CONFIG_PATH="${CONFIG_PATH:-$PROJECT_DIR/configs/runtime.json}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker 未安装或不可用"
  exit 1
fi

DOCKER="docker"
if docker info >/dev/null 2>&1; then
  DOCKER="docker"
elif sudo docker info >/dev/null 2>&1; then
  DOCKER="sudo docker"
else
  echo "docker 不可用（可能需要 sudo 权限或 docker 服务未启动）"
  exit 1
fi

if ! $DOCKER image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
  echo "未找到 openEuler 基础镜像: $BASE_IMAGE"
  echo "请先下载并导入（示例）："
  echo "  wget https://repo.openeuler.org/openEuler-24.03-LTS/docker_img/x86_64/openEuler-docker.x86_64.tar.xz"
  echo "  xz -d openEuler-docker.x86_64.tar.xz"
  echo "  sudo docker load -i openEuler-docker.x86_64.tar"
  exit 1
fi

SMOKE_LLM_BACKEND="${SMOKE_LLM_BACKEND:-}"
SMOKE_LLM_API_KEY="${SMOKE_LLM_API_KEY:-}"
if [ -z "$SMOKE_LLM_API_KEY" ] && [ -f "$CONFIG_PATH" ]; then
  SMOKE_LLM_API_KEY="$(python3 -c "import json;print(json.load(open(\"$CONFIG_PATH\")).get(\"llm\",{}).get(\"api_key\",\"\") )")"
fi
if [ -z "$SMOKE_LLM_BACKEND" ]; then
  SMOKE_LLM_BACKEND=deepseek
fi
if [ -z "$SMOKE_LLM_API_KEY" ]; then
  echo "未提供真实 LLM key：请设置 SMOKE_LLM_API_KEY 或准备 $CONFIG_PATH"
  exit 1
fi

$DOCKER build --build-arg BASE_IMAGE="$BASE_IMAGE" -t "$IMAGE_TAG" .

$DOCKER run --rm \
  -e "SMOKE_LLM_BACKEND=$SMOKE_LLM_BACKEND" \
  -e "SMOKE_LLM_API_KEY=$SMOKE_LLM_API_KEY" \
  "$IMAGE_TAG" \
  bash -lc '
set -euo pipefail
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY
export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost
python3 -m pip install --no-cache-dir -q pytest
python3 -m pytest testing/smoke/test_smoke.py -v
'
