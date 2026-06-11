#!/bin/bash

ensure_docker_available() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker 未安装或不可用"
    exit 1
  fi

  if docker info >/dev/null 2>&1; then
    DOCKER="docker"
  elif sudo docker info >/dev/null 2>&1; then
    DOCKER="sudo docker"
  else
    echo "docker 不可用（可能需要 sudo 权限或 docker 服务未启动）"
    exit 1
  fi
}
