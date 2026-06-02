#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

IMAGE_TAG="${IMAGE_TAG:-agent-runtime-os:openeuler}"
BASE_IMAGE="${BASE_IMAGE:-openeuler-24.03-lts:latest}"
HOST_PORT="${HOST_PORT:-8234}"
CONTAINER_NAME="${CONTAINER_NAME:-agentd-openeuler}"
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

if [ ! -f "$CONFIG_PATH" ]; then
  echo "未找到配置文件: $CONFIG_PATH"
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

$DOCKER build -t "$IMAGE_TAG" .

$DOCKER rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

$DOCKER run --rm \
  --name "$CONTAINER_NAME" \
  -p "${HOST_PORT}:8234" \
  -v "$CONFIG_PATH:/app/configs/runtime.json:ro" \
  -e RUNTIME_CONFIG=/app/configs/runtime.json \
  "$IMAGE_TAG"
