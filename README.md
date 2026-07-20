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
2026-07-19 更新：新增 AgentBackendType/AgentBackendConfig、WorkspaceSpec、ArtifactReference 和 TaskAttempt backend/workspace 字段；新增 backends 基础接口、LegacyLLMBackend、DirectToolBackend、CodexCLIBackend 初版、WorkspaceManager、ArtifactStore、Planner DAG 模型/验证/Materializer，以及 `/runs/{root_task_id}/summary`、`/runs/{root_task_id}/events`、`/artifacts/{artifact_id}`、`/debug/faults/workers/{agent_name}/sigkill` 和 `/dashboard/`。`run_pytest` 返回真实退出码和结构化 passed/failed 摘要。修改前基线依据：`bash scripts/final_check.sh` 中单元/集成前段 168+1+1 通过，Demo reset 因 `target_repo` 内 nobody 文件权限导致 `PermissionError`。
旧 demo 的 `tester` Agent 已显式声明 `write_file`，用于保持既有安全回归测试写入链路与新的 DirectTool 权限校验兼容。
新增 NativePlannerBackend 两阶段流程：Runtime 先执行 repo_scan，再由 LLM 输出 InspectionRequest，Runtime 校验并执行 read_file/search_code，随后 LLM 输出 PlanSpec，由 WorkflowService 校验并通过 Scheduler 入口物化动态子任务。新增 WorkflowService 负责 Planner 子任务创建、Coder/Repair patch 集成基线、Tester 失败触发 Repair、RecoveryContext readonly 记录和 worker 进程组清理。
Docker 默认状态库迁移到 `/runtime/state/state.db`，`final_check.sh` 与 demo 脚本已按 `AGENTD_STATE_DB` 清理 WAL/SHM，避免连续 normal/fault demo 复用旧 Agent 注册状态。
Fake Codex 测试覆盖 success、timeout、JSONL 事件净化和文件变更 patch 生成；timeout 测试清理环境变量，避免影响后续 file_change 用例。
真实 E2E 可通过 `bash scripts/test_real_demo_docker_openeuler.sh` 启动；脚本要求 `OPENAI_API_KEY` 以及 `DEEPSEEK_API_KEY` 或 `LLM_API_KEY` 存在于环境变量，只注入容器运行时，不写入镜像或仓库。
真实 demo 启动脚本会等待 agentd `/metrics` 就绪后再执行 preflight，避免服务未监听时误报失败。
Run summary 的 `leases_reclaimed` 从 ResourceMonitor snapshot 读取，避免直接访问内部实现字段。
Planner parser 支持受控规范化 DeepSeek 等价输出：只接受 `{"plan":[...]}` 到 `PlanSpec.tasks` 的字段名映射，随后仍执行完整 DAG/角色/依赖校验。
CodexCLIBackend 会把相对 `output_schema` 转为仓库根目录下的绝对路径，避免每个 Attempt worktree 中找不到 schema。
2026-07-20 更新：Planner 物化的 coder/tester 子任务默认使用 `fail_closed`，避免 Coder 超时或失败后下游 Tester/Reviewer 误放行；Planner inspection/summary 会进入子任务输入，Codex prompt 同步包含 Task input JSON。PatchArtifact 只在 coder/repair 成功后生成，pytest 工具禁用 bytecode/cache 写入，并且 Git patch 计算排除 `__pycache__` 与 `.pytest_cache`，避免测试运行产物污染补丁。
Planner inspection parser 增加受控兼容：当 DeepSeek 返回 `tasks[].file` 或同类检查任务列表时，Runtime 会提取候选文件并继续执行路径安全校验、文件数量限制和真实 read/search 工具调用。
当 LLM 返回空 InspectionRequest 时，NativePlannerBackend 会从 repo_scan 结果中选择 `app/` 和 `tests/` 下的关键 Python 文件作为受控兜底检查输入，仍限制最多文件数并通过 read_file 工具读取，避免真实 Planner 因格式漂移跳过仓库内容。
真实 Codex/DeepSeek Demo 的 Docker 脚本保留宿主传入的代理环境变量，仅设置 `NO_PROXY/no_proxy=127.0.0.1,localhost`，避免容器内 Codex CLI 直连 OpenAI 时因代理被清空出现 `request timed out`。
当前服务器 Codex 使用 `~/.codex/config.toml` 中的自定义 provider；真实 Demo Docker 脚本会只读挂载宿主 Codex config 到 `/root/.codex/config.toml`，使容器内 Codex 与宿主走同一 provider。Preflight 新增 `codex api` 最小连通性检查，可用 `SKIP_CODEX_PREFLIGHT=1` 显式跳过。
2026-07-20 更新：`scripts/test_docker_openeuler.sh` 也会只读挂载宿主 `~/.codex/config.toml`，并透传 `OPENAI_API_KEY/CODEX_API_KEY`；在同一 OpenEuler 容器内直接执行 `codex --sandbox read-only ... exec --ephemeral --json --skip-git-repo-check "Return the word OK."` 已返回 `OK`，可验证配置生效。
2026-07-20 更新：新增 `applications/incident_repair` LangGraph 代码修复应用骨架，使用同一 Graph State 和 `ExecutionProvider` 切换 direct/runtime/replay；Runtime Provider 复用现有 `AgentRuntimeClient`，SDK 已补齐 `required_capability`、`required_backend`、`timeout_ms`、`task_role`、`trace_id`、`root_task_id`、`idempotency_key` 和 `wait_task`。Direct Provider 使用公平 `asyncio.Semaphore`、共享 worktree/patch 实现、Codex CLI 子进程和 pytest 工具；新增 Run Bundle/Replay manifest、统一事件模型，以及 `testing/perf/comparison` 的统计、成对公平性检查和 CSV/JSON 输出骨架。当前依据：`python3 -m pytest testing/unittest/applications testing/unittest/api/test_client.py -q` 为 17 passed。
2026-07-20 更新：`IncidentGraphRunner` 已使用 `AsyncSqliteSaver.from_conn_string` 接入 SQLite checkpointer，`/demo/runs` 创建 Run Bundle 后会后台执行同一张 LangGraph；OpenEuler 中验证 `Send` 并行 coder 分支汇聚后下游节点只执行一次。`scripts/test_unit.sh` 已纳入 `testing/unittest/applications/`，避免新增应用测试被 Docker 门禁漏跑。新增 `/dashboard/demo.html`、`/dashboard/compare.html`、`/dashboard/benchmarks.html` 最小数据驱动页面，不写死性能结论。当前依据：OpenEuler 单测会实际执行 LangGraph runner 测试。
2026-07-20 更新：Runtime 模式的 LangGraph planner 任务会携带 `graph_managed=true`，Runtime 内部 `WorkflowService` 看到该标记后不再物化业务 DAG，避免 LangGraph 和 AgentRuntime 同时维护一套业务图。`testing/perf/comparison/runner.py` 已能实际跑 fake/direct/runtime 矩阵，自动写出 `run-data/benchmarks/<benchmark_id>/raw_runs.csv`、`summary.csv` 和 `comparison.json`；同时处理 OpenEuler `safe.directory` 问题，避免挂载仓库污染 benchmark 结果。当前依据：OpenEuler 下 fake benchmark 已生成非空 raw/summary CSV，error 字段为空。

实现状态总表见 `docs/implementation_status.md`；进度记录见 `docs/progress.md`。比赛要求范围内的核心机制已经完成；通用抢占、生产级多节点部署和 LLM 语义摘要不在当前实现范围内。

| 模块 | README 声明能力 | 源码实现位置 | 当前状态 | 备注 |
|---|---|---|---|---|
| Core Model | AgentCapability、Task required_capability、状态机、幂等字段 | `aruntime/core/models.py` | 已实现 | Agent/Task 已建模为 runtime 一等公民 |
| Backend | legacy_llm/direct_tool/codex_cli/native_planner 后端配置与 Worker 适配 | `aruntime/backends/*`, `aruntime/worker/agent_worker.py` | 部分实现 | legacy/tool 兼容，Codex CLI 支持 fake 测试；完整 Planner 两阶段和真实 Demo 待扩展 |
| Workspace | Attempt 级 git worktree、PatchArtifact、ArtifactStore | `aruntime/workspace/*` | 部分实现 | patch 和 changed_files 由 git diff 计算 |
| Dashboard/API | Run summary、Run events、Artifact 下载、静态 Dashboard | `aruntime/daemon/main.py`, `aruntime/dashboard/*` | 部分实现 | 原生 HTML/CSS/JS 轮询 REST |
| ACB | Agent lifecycle、timeline、/agents/{agent_name}/acb | `aruntime/core/acb.py`, `aruntime/core/lifecycle.py`, `aruntime/daemon/main.py` | 已实现 | FAILED/LOST 需经 RECOVERING 回 READY |
| Scheduler | fifo/priority/deadline/fair_share/resource_aware/capability_aware/cost_aware/reliability_aware | `aruntime/scheduler/kernel.py` | 已实现 | 支持能力匹配、资源重检和资源阻塞 BLOCKED |
| Dynamic Task | spawn children、DAG、依赖、trace/context 继承、真实 Demo | `aruntime/daemon/main.py`, `aruntime/scheduler/kernel.py`, `examples/production_incident_demo/scripts/run_demo.py` | 已实现 | `/tasks/{task_id}/spawn`, `/children`, `/dag`, `/dependencies`，Demo 至少 12 个子任务 |
| Context | shared/private/readonly/version/diff/compression/prefix metrics | `aruntime/context/manager.py`, `aruntime/context/types.py` | 部分实现 | readonly 用版本追加；LLM 语义摘要为结构化实现 |
| Resource | ResourceLease、LLM 并发、cgroup v2、pressure 读取 | `aruntime/resource/monitor.py`, `aruntime/resource/cgroup.py`, `aruntime/resource/types.py` | 已实现 | 真实 cgroup 依赖宿主权限 |
| Timeout/Kill | timeout_ms、attempt_id、task.timeout trace、cancel、lease 回收、cgroup kill、fallback | `aruntime/daemon/main.py`, `aruntime/resource/cgroup.py`, `aruntime/core/models.py`, `aruntime/worker/agent_worker.py` | 已实现基础闭环 | 超时后进入 TIMEOUT，迟到结果按 active attempt 隔离；通用抢占未实现 |
| Communication | UDS、mailbox、ack、去重、重放、dead-letter、agent_message/cancel/context_update、Worker ACK | `aruntime/comm/message.py`, `aruntime/comm/router.py`, `aruntime/comm/transport.py`, `aruntime/worker/agent_worker.py` | 已实现 | worker 端处理完成后再 ACK，Demo 验证消息只处理一次 |
| Tool Execution | repo_scan、read/write_file、search_code、git_status/diff、run_pytest、run_command | `aruntime/tools/*`, `aruntime/executor/*`, `aruntime/worker/agent_worker.py` | 已实现 | 受控工作区、路径白名单、Shell allowlist、超时和输出限制 |
| Persistence | SQLite/WAL、agents/tasks/attempts/leases/mailbox/trace 恢复 | `aruntime/daemon/store.py`, `aruntime/daemon/recovery_service.py` | 已实现 | 单元测试覆盖 READY/RUNNING 恢复 |
| Heartbeat/Fault | worker heartbeat、restart_budget、fallback attempt、daemon recovery | `aruntime/daemon/fault_service.py`, `aruntime/worker/agent_worker.py`, `aruntime/daemon/recovery_service.py` | 已实现基础 E2E | 记录 worker.lost、worker.isolated、task.fallback，集成测试覆盖恢复 |
| Complex Demo | 真实 agentd、Scheduler、Worker、Tool、pytest、Trace | `examples/production_incident_demo/*`, `testing/integration/test_demo.py` | 已实现 | `make test-demo`、`make test-demo-fault` 校验 `final.patch`、Trace、ACK、fallback、Lease |
| Preemption | 通用任务抢占 | - | 未实现 | 非赛题必要功能 |
| 多节点部署 | 跨节点 Runtime 部署 | - | 未实现 | 当前为单节点 Runtime |
| Benchmark | Scheduler/Context/Fault/IPC/Scalability 输出 CSV/SVG | `testing/perf/*`, `scripts/benchmark_docker_openeuler.sh`, `BENCHMARK.md` | 已实现 | vLLM APC 真实实验需 `VLLM_BASE_URL` |
| LangGraph 对比 | 系统层 Runtime vs 应用层图编排 | `docs/langgraph_compare.md`, `docs/architecture.md` | 已实现 | 文档定位，不引入依赖 |

agentd 接入 LLM：支持 mock / deepseek，可由 configs/runtime.json 或环境变量切换。

ACB（Agent Control Block）：新增 Agent 运行态控制块，集中记录状态、当前任务、资源配额、上下文句柄、故障域、trace_id 和 timeline；状态机纳入 `LOST -> RECOVERING/ISOLATED/KILLED` 闭环，可通过 `/agents/{agent_name}/acb` 查询。

Agent/Task 抽象：`AgentSpec` 支持 `AgentCapability`、`restart_budget`、`fault_domain`、`token_quota`；`TaskSpec` 支持 `required_capability`、`children`、`timeout_ms`、`idempotency_key`、`side_effect_level`、`compensation`。

Agent Runtime Scheduler：支持 `fifo` / `priority` / `resource_aware` / `fair_share` / `deadline` / `capability_aware` / `cost_aware` / `reliability_aware` 策略插件；`kernel` 调度器维护 `ready_queue`、`waiting_queue`、`running_table`、`failed_queue`、`completed_queue`，按资源可用性并发 dispatch，可通过 `SCHEDULER_TYPE=kernel`、`SCHEDULER_POLICY=<policy>` 启用。

调度元数据：任务支持 `priority`、`deadline`、`resource_request`、`token_budget`、`timeout`、结构化 `failure_policy`、`parent_task_id`、`trace_id`；任务查询返回 `queue_wait_ms`、`scheduler_decision_reason`、`resource_block_reason`、`agent_runtime_ms`。

调度观测：`/scheduler/queues` 保持 ready/running/waiting/blocked 快照；`/metrics.scheduler` 输出策略、完整队列、平均排队等待、平均 Agent 运行时和调度决策原因。

故障策略：任务未显式配置时默认不失败级联；显式 `failure_policy` 支持 `fail_open`、`fail_closed`、`retry`、`fallback`、`degrade` 以及 `max_retries`、`fallback_agent`、`timeout_ms`。DAG 边支持 `on_failure`，可对单条依赖边设置 `retry`、`fallback`、`fail_open`、`fail_closed`；无边策略时会按显式任务默认策略处理。

Worker 故障处理：worker 崩溃后 Runtime 标记 Agent 为 `FAILED`，记录 `worker.lost` / `worker.isolated`，释放资源并重启 worker；任务按策略 retry / fallback / degrade / fail_closed 处理，下游任务按边 `on_failure` 决策。超时任务会发送 `cancel_task`，等待宽限期后 kill worker/cgroup，并校验 `attempt_id` 丢弃迟到结果。

受控工具执行：worker 支持 `__tool` 请求直达真实工具执行层，内置 `repo_scan`、`read_file`、`search_code`、`write_file`、`git_status`、`git_diff`、`run_pytest`、`run_command`。默认工作区路径受限，禁止越界访问，Shell 仅允许白名单命令，命令超时和输出大小受控。

故障演示：生命周期集成测试覆盖 Coder A worker 崩溃后，Runtime 按 `fallback_agent` 自动切换到 Coder B，Tester 依赖任务继续执行，整体任务不崩溃。

统一资源管理：Runtime 统一管理 CPU、Memory、LLM Concurrency、Token、Tool、KV Cache、Network。资源模型包含 `ResourceClass`、`ResourceQuota`、`ResourceRequest`、`ResourceUsage`、`ResourceLease`、`ResourceReclaimer`；`ResourceMonitor.acquire/release/reclaim/can_allocate` 使用同一进程内锁保护，避免并发 `can_allocate -> lease -> usage` 超配；调度前检查资源，执行前申请 lease，执行中监控资源，执行后释放资源，worker 崩溃和 daemon 恢复路径会回收失效 lease。

资源感知调度：支持 `resource_aware` 模式，基于 `psutil` 采集 CPU / 内存，支持全局与单 Agent 的 LLM 并发控制；资源阻塞任务唤醒前会重新检查资源，排序分数使用 memory/token/LLM 比例归一化，并在 `scheduler_decision_reason` 输出 `memory_ratio`、`token_ratio`、`llm_ratio`、`final_score`；`/metrics.resource` 输出 usage、leases、reclaimed。

上下文优化：从 `context_id` 字典复用升级为可量化机制。Semantic Context 输出 `shared_context`、`private_context`、`readonly_context`、`context_version`、`context_diff`、`summary`；压缩后继续维护增量上下文，后续 Repair/Reviewer 信息不会被丢弃；Execution Context 输出 `shared_prefix_hash`、`full_execution_context_hash`、`prefix_block_id`、`reuse_count`、`input_token_before`、`input_token_after`、`shared_prefix_hit`、`full_context_hit`。

LLM 统计：LLM Gateway 返回 `input_tokens`、`output_tokens`、`total_tokens`、`latency_ms`、`prefix_cache_hit`；任务查询返回 `llm_usage`，`/metrics.llm` 汇总调用 token 和延迟。

实验指标：`/metrics.experiments` 输出 `token_saving_ratio`、`context_build_time_ms`、`prefix_hit_ratio`、`llm_latency_ms`。

系统级可观测性：每个任务自动生成 `trace_id`，每次 Agent worker 执行生成 `agent.execute` span；LLM、context、IPC、resource 操作写入 trace event。`/tasks/{task_id}/trace` 输出 JSON trace，包含 `critical_path`、`queue_wait_ms`、`llm_calls`、`token_used`、`context_hit_ratio`、`retry_count`；`/metrics.histograms` 输出 queue wait、Agent runtime、LLM latency、context build time、resource lease 直方图。

Benchmark：根目录 `BENCHMARK.md` 记录三组真实性能实验：调度策略、上下文优化、容错策略；通过 `bash scripts/benchmark_docker_openeuler.sh` 在 openEuler Docker 中生成，并输出 `benchmark/results/raw.csv`、`benchmark/results/summary.csv` 与 `benchmark/figures/*.svg`。

Agent 生命周期管理：支持注册、提交任务、查询任务状态。

任务查询：`/tasks/{task_id}` 返回任务结果，同时包含 Agent runtime 摘要（agent_status、current_task_id、trace_id）。

Agent 执行模型：每个 Agent 为独立进程（worker），agentd 通过 UDS 下发任务并回传结果。

Agent 间通信：UDS 流式通信 + agentd 路由（在线 push，离线 mailbox，上线补发）。MessageRouter 使用 asyncio.Lock 保护连接表和 mailbox，锁内只读写内存状态，网络 drain、连接等待均在锁外执行；慢连接 drain 不阻塞其他 Agent mailbox 操作，断线写失败会回投 mailbox，同名重连不会被旧连接注销覆盖；消息 ACK、context_update ACK 和 cancel ACK 统一走单连接锁。HTTP 仍保留 /messages 作为调试接口。

任务状态：TaskDefinition / TaskControlBlock / TaskAttempt 三层拆分，TCB 作为唯一运行时状态源，状态转换统一走 FSM，fallback 通过新 attempt 记录，不改原始任务归属。

调度：提交任务进入 Agent 队列，不再因为同 Agent 忙碌直接拒绝；调度循环用事件唤醒，使用全局和单 Agent semaphore 控制并发，并记录调度选择和阻塞原因。

资源控制：CgroupManager 负责 create / attach / update / read_stats / kill / cleanup，控制 cpu.max、cpu.weight、memory.high、memory.max、pids.max，并读取 cpu.stat、memory.events、cgroup.events、cpu.pressure、memory.pressure。Agent 可配置 `memory_high_bytes`、`pids_max`；worker 退出会清理 cgroup；`CGROUP_STRICT=true` 时 cgroup 绑定失败会拒绝任务执行。

上下文：指标名称改为 logical context reuse hit；压缩改为结构化摘要，保留压缩前版本，支持回滚，readonly 采用只增不改。

动态任务：Runtime 提供 `/tasks/{task_id}/spawn`、`/tasks/{task_id}/children`、`/tasks/{task_id}/dag`、`/tasks/{task_id}/dependencies`，支持运行中创建子任务、继承 trace_id/context_id、按依赖进入 READY 或等待。

资源隔离与观测：支持 cgroup v2 绑定 worker（可选），并在 `/metrics.cgroups` 输出绑定结果、cpu.stat、memory.events 和 PSI pressure；`/metrics.resource` 输出资源 usage、leases、reclaimed 快照。

持久化与恢复：agentd 使用 SQLite/WAL 持久化 agents、tasks、task_attempts、resource_leases、mailbox_messages、trace_events；启动恢复时 READY/PENDING 任务重新入队，RUNNING 任务经 ORPHANED 标记后转 READY 重试，并释放失效资源租约。

故障治理：worker 支持 heartbeat；agentd 记录 restart_count、restart_budget、circuit breaker、fault_domain 和 fallback attempt 历史；retry 使用指数 backoff，deadline 过期任务在 dispatch 前 CANCELLED，fallback 不修改原始 task.agent_name。

UDS 安全：worker 启动时注入一次性认证 token，UDS 注册校验 token 并读取 SO_PEERCRED；socket 权限设为 0660；单条消息限制大小，task_result 使用严格 schema、message_id、ack 和去重；mailbox 满后进入 dead-letter queue。

daemon 拆分：新增 daemon/app.py、store.py、recovery_service.py、fault_service.py、worker_service.py，将持久化、恢复、故障状态和 worker 启动日志从 main.py 中拆出。集成测试直接拉起 agentd，并用 `/metrics` 轮询确认就绪；资源感知测试使用独立 `AGENTD_STATE_DB`，避免共享状态库互相污染。

可观测性：worker stdout/stderr 写入 `AGENTD_LOG_DIR` 下独立日志文件，agentd 写结构化 JSONL；`/metrics` 增加 persistence 与 faults 快照，trace event 同步持久化。

## 测试
### 单元测试(testing/unittest/)

core/test_lifecycle_core.py:测试Agent生命周期状态。

验证状态转换的合法性（如CREATED->READY->RUNNING->COMPLETED）以及非法转换能否正确拦截

core/test_acb.py:测试 ACB 运行态控制块。

验证 ACB 从 AgentSpec 初始化、状态转换 timeline 记录、资源配额和上下文句柄序列化。

core/test_models.py:测试 AgentCapability、Task required_capability、timeout_ms、幂等和副作用字段。

core/test_agent_fsm.py:测试 ACB 状态机非法迁移、FAILED/LOST->RECOVERING->READY 和 timeline。

scheduler/test_dag.py:DAG 调度器单元测试（依赖、动态任务、默认不级联、显式 fail-closed/fail-open、边 on_failure fail_open、拓扑排序）。

scheduler/test_kernel.py:Kernel/Agent Runtime Scheduler 单元测试（ready/waiting/running/failed/completed 队列、依赖唤醒、priority/deadline/fair_share/resource_aware 策略、资源阻塞重检、归一化调度指标、默认不级联、显式 fail-closed/fail-open、边 on_failure fail_open）。

scheduler/test_capability_match.py:能力调度单元测试（planner/code/language/reliability/resource BLOCKED）。

scheduler/test_resource_aware.py:资源感知调度器单元测试（资源检查、LLM 并发控制、FIFO/DAG 包装行为）。

resource/test_resources.py:统一资源模型单元测试（ResourceClass、ResourceRequest、ResourceUsage、ResourceLease、ResourceReclaimer）。

context/test_manager.py:上下文管理器单元测试（上下文复用、shared/private/readonly 隔离、context_diff、summary、压缩、Semantic Context、Execution Context、token/cache metrics）。

context/test_context_permissions.py:上下文权限单元测试（private 隔离、readonly 版本追加、rollback diff）。

llm/test_gateway.py:LLM Gateway 统计单元测试（input/output/total tokens、latency、prefix_cache_hit）。

observability/test_trace.py:系统级 trace 单元测试（trace_id、critical_path、queue_wait_ms、llm_calls、token_used、context_hit_ratio、retry_count、span/event JSON）。

perf/test_benchmark.py:Benchmark 一键测试入口，调用 `testing/perf/suite.py` 生成 P0/P1/P2 benchmark 报告、原始 CSV、汇总 CSV 和 SVG 图表。
perf/metrics.py:Benchmark 统计工具（mean、stdev、P50/P95/P99、95% CI、CSV、SVG）。
perf/suite.py:Benchmark 编排器，覆盖 FIFO 并发 vs resource-aware 并发、cgroup、vLLM APC、故障注入、通信、扩展性、E2E workflow 和 Runtime 开销。
perf/workloads.py:Benchmark workload 辅助模块。

api/test_client.py:SDK（AgentRuntimeClient）单元测试。

core/test_tcb.py:TCB / TaskAttempt 单元测试。
comm/test_router.py:消息路由器（mailbox）单元测试，覆盖离线并发路由、断线回投、同名重连，并用 asyncio.wait_for 检测死锁。
comm/test_ack_dedup.py:可靠消息语义单元测试，覆盖 ACK、message_id 去重、未 ACK 重放。
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
