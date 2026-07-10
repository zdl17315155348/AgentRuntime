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

带上下文的任务示例：

```bash
curl -s -X POST http://127.0.0.1:8234/tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "agent_name":"docker_test_1",
    "context_id":"ctx-code-repair-1",
    "task_input":{
      "request":"制定修复计划",
      "context":{
        "shared":{"repo":"agent-runtime-os"},
        "private":{"note":"planner local note"}
      }
    }
  }'
```

将返回中的 `task_id` 替换到下面命令中：

```bash
curl -s http://127.0.0.1:8234/tasks/<task_id>
```

成功判定：`status` 为 `SUCCESS`，并且 `result.output` 为真实模型输出（例如 `OK`）。

## 当前进度
agentd 接入 LLM：支持 mock / deepseek，可由 configs/runtime.json 或环境变量切换。

ACB（Agent Control Block）：新增 Agent 运行态控制块，集中记录状态、当前任务、资源配额、上下文句柄、故障域、trace_id 和 timeline；可通过 `/agents/{agent_name}/acb` 查询。

调度器：支持 fifo / dag / kernel。dag 支持任务依赖和动态任务；kernel 支持 ready / running / waiting / blocked 队列，可通过 `SCHEDULER_TYPE=kernel` 启用，并通过 `/scheduler/queues` 查询队列快照。

故障隔离：任务默认 `failure_policy=isolate`，单个 Agent 任务失败不会默认级联失败下游任务；显式设置 `failure_policy=fail-closed` 时才阻断强依赖下游。

资源感知调度：支持 `resource_aware` 模式，基于 `psutil` 采集 CPU / 内存，支持全局与单 Agent 的 LLM 并发控制。

上下文管理：支持按 `context_id` 复用上下文，区分 shared / private 数据，支持超阈值压缩；新增 Semantic Context（version、shared/private keys）和 Execution Context（prefix cache key、token_count、reused_tokens、saved_tokens、cache_hit_ratio）统计，并在 `/metrics` 输出 token/cache 指标。

Agent 生命周期管理：支持注册、提交任务、查询任务状态。

任务查询：`/tasks/{task_id}` 返回任务结果，同时包含 Agent runtime 摘要（agent_status、current_task_id、trace_id）。

Agent 执行模型：每个 Agent 为独立进程（worker），agentd 通过 UDS 下发任务并回传结果。

Agent 间通信：UDS 流式通信 + agentd 路由（在线 push，离线 mailbox，上线补发）。HTTP 仍保留 /messages 作为调试接口。

资源隔离与观测：支持 cgroup v2 绑定 worker（可选），并在 /metrics 输出 worker 存活统计与 resource 资源快照。

## 测试
### 单元测试(testing/unittest/)

core/test_lifecycle_core.py:测试Agent生命周期状态。

验证状态转换的合法性（如CREATED->READY->RUNNING->COMPLETED）以及非法转换能否正确拦截

core/test_acb.py:测试 ACB 运行态控制块。

验证 ACB 从 AgentSpec 初始化、状态转换 timeline 记录、资源配额和上下文句柄序列化。

scheduler/test_dag.py:DAG 调度器单元测试（依赖、动态任务、默认故障隔离、显式 fail-closed、拓扑排序）。

scheduler/test_kernel.py:Kernel 调度器单元测试（ready/running/waiting/blocked 队列、依赖唤醒、priority 排序、默认故障隔离、显式 fail-closed）。

scheduler/test_resource_aware.py:资源感知调度器单元测试（资源检查、LLM 并发控制、FIFO/DAG 包装行为）。

context/test_manager.py:上下文管理器单元测试（上下文复用、shared/private 隔离、压缩、Semantic Context、Execution Context、token/cache metrics）。

api/test_client.py:SDK（AgentRuntimeClient）单元测试。

comm/test_router.py:消息路由器（mailbox）单元测试。


daemon/test_lifecycle.py:测试通过agentd API操作时Agent生命周期是否按预期流转。

覆盖创建 Agent、ACB 查询、提交任务、依赖任务校验、DAG 依赖阻塞、故障隔离、显式 fail-closed、消息收发等场景。

daemon/test_resource_aware.py:资源感知调度集成测试。

覆盖 `/metrics` 资源快照、资源感知模式下任务执行、多任务执行、DAG 依赖执行与 Agent 状态流转等场景。


daemon/test_api.py:测试agentd各API端点的正确性。

验证注册、提交、查询等接口的请求和响应格式是否正确。

### Docker openEuler 测试入口

统一测试入口为 `scripts/test_docker_openeuler.sh`，在 openEuler Docker 容器中执行单元测试、生命周期集成测试、资源感知集成测试以及 smoke 测试。
