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

Agent Runtime Scheduler：支持 `fifo` / `priority` / `resource_aware` / `fair_share` / `deadline` 策略插件；`kernel` 调度器维护 `ready_queue`、`waiting_queue`、`running_table`、`failed_queue`、`completed_queue`，按资源可用性并发 dispatch，可通过 `SCHEDULER_TYPE=kernel`、`SCHEDULER_POLICY=<policy>` 启用。

调度元数据：任务支持 `priority`、`deadline`、`resource_request`、`token_budget`、`timeout`、结构化 `failure_policy`、`parent_task_id`、`trace_id`；任务查询返回 `queue_wait_ms`、`scheduler_decision_reason`、`resource_block_reason`、`agent_runtime_ms`。

调度观测：`/scheduler/queues` 保持 ready/running/waiting/blocked 快照；`/metrics.scheduler` 输出策略、完整队列、平均排队等待、平均 Agent 运行时和调度决策原因。

故障策略：任务默认不失败级联；`failure_policy` 支持 `fail_open`、`fail_closed`、`retry`、`fallback`、`degrade` 以及 `max_retries`、`fallback_agent`、`timeout_ms`。DAG 边支持 `on_failure`，可对单条依赖边设置 `retry`、`fallback`、`fail_open`、`fail_closed`。

Worker 故障处理：worker 崩溃后 Runtime 标记 Agent 为 `FAILED`，记录 `worker.isolated`，释放资源并重启 worker；任务按策略 retry / fallback / degrade / fail_closed 处理，下游任务按边 `on_failure` 决策。

故障演示：生命周期集成测试覆盖 Coder A worker 崩溃后，Runtime 按 `fallback_agent` 自动切换到 Coder B，Tester 依赖任务继续执行，整体任务不崩溃。

统一资源管理：Runtime 统一管理 CPU、Memory、LLM Concurrency、Token、Tool、KV Cache、Network。资源模型包含 `ResourceClass`、`ResourceQuota`、`ResourceRequest`、`ResourceUsage`、`ResourceLease`、`ResourceReclaimer`；`ResourceMonitor.acquire/release/reclaim/can_allocate` 使用同一进程内锁保护，避免并发 `can_allocate -> lease -> usage` 超配；调度前检查资源，执行前申请 lease，执行中监控资源，执行后释放资源，worker 崩溃和 daemon 恢复路径会回收失效 lease。

资源感知调度：支持 `resource_aware` 模式，基于 `psutil` 采集 CPU / 内存，支持全局与单 Agent 的 LLM 并发控制；`/metrics.resource` 输出 usage、leases、reclaimed。

上下文优化：从 `context_id` 字典复用升级为可量化机制。Semantic Context 输出 `shared_context`、`private_context`、`readonly_context`、`context_version`、`context_diff`、`summary`；Execution Context 输出 `prefix_hash`、`prefix_block_id`、`reuse_count`、`input_token_before`、`input_token_after`、`cache_hit`。

LLM 统计：LLM Gateway 返回 `input_tokens`、`output_tokens`、`total_tokens`、`latency_ms`、`prefix_cache_hit`；任务查询返回 `llm_usage`，`/metrics.llm` 汇总调用 token 和延迟。

实验指标：`/metrics.experiments` 输出 `token_saving_ratio`、`context_build_time_ms`、`prefix_hit_ratio`、`llm_latency_ms`。

系统级可观测性：每个任务自动生成 `trace_id`，每次 Agent worker 执行生成 `agent.execute` span；LLM、context、IPC、resource 操作写入 trace event。`/tasks/{task_id}/trace` 输出 JSON trace，包含 `critical_path`、`queue_wait_ms`、`llm_calls`、`token_used`、`context_hit_ratio`、`retry_count`；`/metrics.histograms` 输出 queue wait、Agent runtime、LLM latency、context build time、resource lease 直方图。

Benchmark：根目录 `BENCHMARK.md` 记录调度公平对照、cgroup 隔离/压力、vLLM APC、容错故障注入、通信公平对照、扩展性、复杂 E2E 和 Runtime 开销实验；通过 `bash scripts/benchmark_docker_openeuler.sh` 在 openEuler Docker 中生成，并输出 `benchmark/results/raw.csv`、`benchmark/results/summary.csv` 与 `benchmark/figures/*.svg`。真实 vLLM APC 依赖 `VLLM_BASE_URL`，真实 cgroup 隔离和压力采集依赖宿主机 cgroup v2 写权限，环境不可用时报告会明确标记降级/跳过。

Agent 生命周期管理：支持注册、提交任务、查询任务状态。

任务查询：`/tasks/{task_id}` 返回任务结果，同时包含 Agent runtime 摘要（agent_status、current_task_id、trace_id）。

Agent 执行模型：每个 Agent 为独立进程（worker），agentd 通过 UDS 下发任务并回传结果。

Agent 间通信：UDS 流式通信 + agentd 路由（在线 push，离线 mailbox，上线补发）。MessageRouter 使用 asyncio.Lock 保护连接表和 mailbox，锁内只读写内存状态，网络 drain、连接等待均在锁外执行；断线写失败会回投 mailbox，同名重连不会被旧连接注销覆盖。HTTP 仍保留 /messages 作为调试接口。

任务状态：TaskDefinition / TaskControlBlock / TaskAttempt 三层拆分，TCB 作为唯一运行时状态源，状态转换统一走 FSM，fallback 通过新 attempt 记录，不改原始任务归属。

调度：提交任务进入 Agent 队列，不再因为同 Agent 忙碌直接拒绝；调度循环用事件唤醒，使用全局和单 Agent semaphore 控制并发，并记录调度选择和阻塞原因。

资源控制：CgroupManager 负责 create / attach / update / read_stats / kill / cleanup，控制 cpu.max、cpu.weight、memory.high、memory.max、pids.max，并读取 cpu.stat、memory.events、cgroup.events、cpu.pressure、memory.pressure。Agent 可配置 `memory_high_bytes`、`pids_max`；worker 退出会清理 cgroup；`CGROUP_STRICT=true` 时 cgroup 绑定失败会拒绝任务执行。

上下文：指标名称改为 logical context reuse hit；压缩改为结构化摘要，保留压缩前版本，支持回滚，readonly 采用只增不改。

资源隔离与观测：支持 cgroup v2 绑定 worker（可选），并在 `/metrics.cgroups` 输出绑定结果、cpu.stat、memory.events 和 PSI pressure；`/metrics.resource` 输出资源 usage、leases、reclaimed 快照。

持久化与恢复：agentd 使用 SQLite/WAL 持久化 agents、tasks、task_attempts、resource_leases、mailbox_messages、trace_events；启动恢复时 READY/PENDING 任务重新入队，RUNNING 任务经 ORPHANED 标记后转 READY 重试，并释放失效资源租约。

故障治理：worker 支持 heartbeat；agentd 记录 restart_count、restart_budget、circuit breaker、fault_domain 和 fallback attempt 历史；retry 使用指数 backoff，deadline 过期任务在 dispatch 前 CANCELLED，fallback 不修改原始 task.agent_name。

UDS 安全：worker 启动时注入一次性认证 token，UDS 注册校验 token 并读取 SO_PEERCRED；socket 权限设为 0660；单条消息限制大小，task_result 使用严格 schema、message_id、ack 和去重；mailbox 满后进入 dead-letter queue。

daemon 拆分：新增 daemon/app.py、store.py、recovery_service.py、fault_service.py、worker_service.py，将持久化、恢复、故障状态和 worker 启动日志从 main.py 中拆出。

可观测性：worker stdout/stderr 写入 `AGENTD_LOG_DIR` 下独立日志文件，agentd 写结构化 JSONL；`/metrics` 增加 persistence 与 faults 快照，trace event 同步持久化。

## 测试
### 单元测试(testing/unittest/)

core/test_lifecycle_core.py:测试Agent生命周期状态。

验证状态转换的合法性（如CREATED->READY->RUNNING->COMPLETED）以及非法转换能否正确拦截

core/test_acb.py:测试 ACB 运行态控制块。

验证 ACB 从 AgentSpec 初始化、状态转换 timeline 记录、资源配额和上下文句柄序列化。

scheduler/test_dag.py:DAG 调度器单元测试（依赖、动态任务、默认不级联、显式 fail-closed、边 on_failure fail_open、拓扑排序）。

scheduler/test_kernel.py:Kernel/Agent Runtime Scheduler 单元测试（ready/waiting/running/failed/completed 队列、依赖唤醒、priority/deadline/fair_share/resource_aware 策略、资源阻塞等待、调度指标、默认不级联、显式 fail-closed、边 on_failure fail_open）。

scheduler/test_resource_aware.py:资源感知调度器单元测试（资源检查、LLM 并发控制、FIFO/DAG 包装行为）。

resource/test_resources.py:统一资源模型单元测试（ResourceClass、ResourceRequest、ResourceUsage、ResourceLease、ResourceReclaimer）。

context/test_manager.py:上下文管理器单元测试（上下文复用、shared/private/readonly 隔离、context_diff、summary、压缩、Semantic Context、Execution Context、token/cache metrics）。

llm/test_gateway.py:LLM Gateway 统计单元测试（input/output/total tokens、latency、prefix_cache_hit）。

observability/test_trace.py:系统级 trace 单元测试（trace_id、critical_path、queue_wait_ms、llm_calls、token_used、context_hit_ratio、retry_count、span/event JSON）。

perf/test_benchmark.py:Benchmark 一键测试入口，调用 `testing/perf/suite.py` 生成 P0/P1/P2 benchmark 报告、原始 CSV、汇总 CSV 和 SVG 图表。
perf/metrics.py:Benchmark 统计工具（mean、stdev、P50/P95/P99、95% CI、CSV、SVG）。
perf/suite.py:Benchmark 编排器，覆盖 FIFO 并发 vs resource-aware 并发、cgroup、vLLM APC、故障注入、通信、扩展性、E2E workflow 和 Runtime 开销。
perf/workloads.py:Benchmark workload 辅助模块。

api/test_client.py:SDK（AgentRuntimeClient）单元测试。

core/test_tcb.py:TCB / TaskAttempt 单元测试。
comm/test_router.py:消息路由器（mailbox）单元测试，覆盖离线并发路由、断线回投、同名重连，并用 asyncio.wait_for 检测死锁。
comm/test_transport.py:UDS 单元测试，覆盖上线补发、在线推送、0660 权限、token 注册和消息大小限制；本地沙箱不允许创建 UNIX socket 时跳过，Docker OpenEuler 中验证。
daemon/test_store_recovery.py:SQLite/WAL 持久化与恢复单元测试，覆盖 agents/tasks/task_attempts/trace_events 保存，以及 RUNNING->ORPHANED->READY 恢复。
resource/test_resources.py:资源租约、LLM 并发、并发 acquire 防超配、cgroup manager 单元测试。
context/test_manager.py:上下文结构化压缩、logical context reuse、回滚单元测试。


daemon/test_lifecycle.py:测试通过agentd API操作时Agent生命周期是否按预期流转。

覆盖创建 Agent、ACB 查询、提交任务、依赖任务校验、DAG 依赖阻塞、故障隔离、显式 fail-closed、fallback 自动切换 Coder、消息收发等场景。

daemon/test_resource_aware.py:资源感知调度集成测试。

覆盖 `/metrics` 资源快照、资源感知模式下任务执行、多任务执行、DAG 依赖执行与 Agent 状态流转等场景。


daemon/test_api.py:测试agentd各API端点的正确性。

验证注册、提交、查询等接口的请求和响应格式是否正确。

### Docker openEuler 测试入口

统一测试入口为 `scripts/test_docker_openeuler.sh`，在 openEuler Docker 容器中执行单元测试、生命周期集成测试、资源感知集成测试以及 smoke 测试。
脚本在 smoke 前会清理 8234 端口、默认 UDS socket 和默认 SQLite 状态库，避免复用前序 mock daemon 或旧恢复状态。

Benchmark 入口为 `scripts/benchmark_docker_openeuler.sh`，在 openEuler Docker 容器中执行 `testing/perf/test_benchmark.py` 并复制生成根目录 `BENCHMARK.md`。本地执行 `python3 -m pytest testing/perf/test_benchmark.py -q` 会同步生成 `benchmark/results/raw.csv`、`benchmark/results/summary.csv` 和 `benchmark/figures/*.svg`。
