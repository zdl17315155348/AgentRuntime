# AgentRuntimeOS

面向多智能体的操作系统运行时

## 如何启动
agent-runtime-os/scripts/start_agentd.sh:启动agentd service（后续用systemctl后台运行服务）

agent-runtime-os/scripts/submit.sh:提交agent任务

## Docker(openEuler) 运行（完整步骤）
目标：在 openEuler 用户态环境中运行 agentd，并通过真实 DeepSeek LLM 走完端到端链路。

### 1. 前置条件
- Ubuntu 上已安装并可用 Docker（`docker --version` 能输出版本）
- 项目根目录：`/home/zdl/projects/agent-runtime-os`
- 已准备好 `configs/runtime.json`（包含真实 LLM 配置，不要提交到仓库）

`configs/runtime.json` 示例结构：

```json
{
  "llm": {
    "backend": "deepseek",
    "api_key": "YOUR_KEY",
    "model": "deepseek-chat",
    "temperature": 0.1,
    "max_tokens": 2048
  }
}
```

### 2. 获取 openEuler Docker 基础镜像
如果网络能访问 Docker Hub：

```bash
sudo docker pull openeuler/openeuler:24.03-lts
```

如果网络无法访问 Docker Hub（离线导入方式，已验证可行）：

```bash
wget https://repo.openeuler.org/openEuler-24.03-LTS/docker_img/x86_64/openEuler-docker.x86_64.tar.xz
xz -d openEuler-docker.x86_64.tar.xz
sudo docker load -i openEuler-docker.x86_64.tar
sudo docker images | grep openeuler
```

离线导入后的镜像名通常为：`openeuler-24.03-lts:latest`。

### 3. 准备 Dockerfile（不提交仓库也可）
如果仓库里已经有 `Dockerfile`，可直接使用；否则在项目根目录创建一个 `Dockerfile`，内容如下：

```Dockerfile
FROM openeuler-24.03-lts:latest

WORKDIR /app

RUN dnf -y install python3 python3-pip && dnf clean all

COPY . /app

RUN python3 -m pip install --no-cache-dir -r requirements.txt

EXPOSE 8234

CMD ["python3", "-m", "uvicorn", "aruntime.daemon.main:app", "--host", "0.0.0.0", "--port", "8234", "--log-level", "info"]
```

### 4. 构建镜像并启动 agentd
在项目根目录执行：

```bash
sudo docker build -t agent-runtime-os:openeuler .
sudo docker run --rm -p 8234:8234 \
  -v $(pwd)/configs/runtime.json:/app/configs/runtime.json:ro \
  -e RUNTIME_CONFIG=/app/configs/runtime.json \
  agent-runtime-os:openeuler
```

### 5. 验证端到端链路（真实 LLM）
另开一个终端执行：

```bash
curl -s http://127.0.0.1:8234/metrics

curl -s -X POST http://127.0.0.1:8234/agents \
  -H 'Content-Type: application/json' \
  -d '{"agent_name":"docker_test_1","role":"docker-smoke","system_prompt":"请简短回答"}'

curl -s -X POST http://127.0.0.1:8234/tasks \
  -H 'Content-Type: application/json' \
  -d '{"agent_name":"docker_test_1","task_input":{"request":"请只返回 OK"}}'
```

将返回中的 `task_id` 替换到下面命令中：

```bash
curl -s http://127.0.0.1:8234/tasks/<task_id>
```

成功判定：`status` 为 `SUCCESS`，并且 `result.output` 为真实模型输出（例如 `OK`）。

## 当前进度
agentd 接入 LLM：支持 mock / deepseek，可由 configs/runtime.json 或环境变量切换。

调度器：支持 fifo / dag。dag 支持任务依赖、动态任务、失败级联。

Agent 生命周期管理：支持注册、提交任务、查询任务状态。

Agent 间通信：agentd 中转的消息邮箱模型（POST /messages，GET /messages/{agent_name} 拉取并消费）。

## 测试
### 单元测试(testing/unittest/)

core/test_lifecycle_core.py:测试Agent生命周期状态。

验证状态转换的合法性（如CREATED->READY->RUNNING->COMPLETED）以及非法转换能否正确拦截

scheduler/test_dag.py:DAG 调度器单元测试（依赖、动态任务、失败级联、拓扑排序）。

api/test_client.py:SDK（AgentRuntimeClient）单元测试。

comm/test_router.py:消息路由器（mailbox）单元测试。


daemon/test_lifecycle.py:测试通过agentd API操作时Agent生命周期是否按预期流转。

覆盖创建 Agent、提交任务、依赖任务校验、DAG 依赖阻塞与失败级联、消息收发等场景。


daemon/test_api.py:测试agentd各API端点的正确性。

验证注册、提交、查询等接口的请求和响应格式是否正确。
