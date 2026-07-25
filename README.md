# AgentRuntimeOS

面向多智能体的操作系统运行时。

## 项目框架

- `aruntime/`：运行时核心，包含 daemon、scheduler、worker、resource、context、llm、dashboard。
- `applications/incident_repair/`：LangGraph 应用层，负责 planner、coder、tester、reviewer、repair、integrate 闭环。
- `examples/production_incident_demo/`：生产事故 demo、目标仓库、隐藏测试和运行脚本。
- `testing/`：单元、集成、smoke 和 benchmark 测试框架。
- `deploy/`：openEuler 容器与编排文件。

## 测试框架

```bash
python3 -m pytest testing/unittest -q
python3 -m pytest testing/unittest/applications -q
python3 -m pytest testing/integration -q
bash scripts/test_docker_openeuler.sh
python3 scripts/final_acceptance.py
python3 scripts/final_acceptance.py --require-real
python3 scripts/final_board_check.py
```

## 启动方式

本地启动 agentd：

```bash
python3 -m aruntime.daemon.main
```

Docker(openEuler) 启动：

```bash
bash scripts/start_agentd_docker.sh
```

Dashboard：

```text
http://127.0.0.1:8234/dashboard/demo.html
http://127.0.0.1:8234/dashboard/compare.html
http://127.0.0.1:8234/dashboard/benchmarks.html
```

运行结果：

```text
http://127.0.0.1:8234/runs/<run_id>/summary
http://127.0.0.1:8234/runs/<run_id>/events?after_id=0
http://127.0.0.1:8234/demo/runs/<run_id>/stream
```

demo：

```bash
bash examples/production_incident_demo/scripts/run_normal.sh
bash examples/production_incident_demo/scripts/run_fault.sh
```

## 封板进度

- [x] P0-1 Runtime 侧 Codex 结构化结果解析：`codex_cli` 输出必须是 JSON object，coder/repair 使用 `CoderResultModel` 校验，reviewer 使用 `ReviewSummaryModel` 校验，非法 JSON 和空输出明确失败；依据：`python3 -m pytest testing/unittest/applications/test_incident_execution_provider.py -q`。
- [x] P0-2 Runtime 异构 Backend 集成测试：覆盖 `architect/native_planner`、`coder_a/codex_cli`、`tester/direct_tool`、`reviewer` 只读 Codex 沙箱、`backend_started` 真实类型和 coder 不回退 `legacy_llm`；依据：`python3 -m pytest testing/integration/test_worker_backend_selection.py testing/unittest/core/test_models.py -q`。
- [x] P0-3 Tester 系统状态与业务状态：pytest 失败保持 Runtime Task `SUCCESS` 并保留 `returncode != 0`，路由进入 `repair`，worker 崩溃为 `FAILED`，pytest 超时为 `TIMEOUT`，工具权限错误为系统执行错误；依据：`python3 -m pytest testing/unittest/applications/test_incident_execution_provider.py testing/unittest/applications/test_incident_graph_routing.py -q`。
- [x] P1-5 openEuler 镜像强制 Codex 依赖：`deploy/Dockerfile.openeuler` 使用 `COPY third_party/codex/codex /usr/local/bin/codex`，构建时执行 `chmod`、`test -x`、`codex --version` 并记录 SHA-256 `ac06f492f3ded7a8e2f36dc961e3cc5276a3c4841a2695d4681d0557c5b30e41`；本地二进制依据：`codex-cli 0.142.5`、`ELF 64-bit x86-64`。
- [x] P1-6/P1-7 openEuler 脚本和 Preflight：`start_agentd_docker.sh` 与 `test_docker_openeuler.sh` 显式使用 `deploy/Dockerfile.openeuler`，key 仅通过环境变量传入，挂载 runtime config、workspace、artifact、state、log 目录，支持 `AGENTD_ENABLE_FAULT_INJECTION`，preflight 检查 Codex/DeepSeek 真实模式、agentd/dashboard 和目录写权限。
- [x] P0-4 integration 顺序稳定性：`test_worker_fallback` 在需要时自启隔离状态库的 mock agentd，避免完整 `testing/integration` 顺序运行时连接竞争；依据：openEuler 容器内 `python3 -m pytest testing/integration -q` 为 `7 passed`。
- [x] P1-7 Preflight 错误可观测性：外部命令超时返回明确 `FAIL timeout after Ns`，不再 traceback。
- [x] P1-7 Preflight 仓库导入路径：脚本启动时加入仓库根目录到 `sys.path`，确保 openEuler 容器任意工作目录下都能导入 `aruntime`。
- [x] P2-9 Codex 非交互调用：Direct 和 Runtime Codex 子进程显式关闭 stdin，避免真实 CLI 在非 TTY 容器执行时读取额外输入；依据：`python3 -m pytest testing/unittest/backends/test_codex_command.py testing/unittest/backends/test_codex_timeout.py testing/unittest/backends/test_codex_file_change.py -q`。
- [x] P2-9 Codex 真实对话确认：openEuler 容器内 `read-only` 最小对话返回 `thread.started`、`turn.completed`、`agent_message` 和 `final.json`，说明认证与对话正常。
- [x] P1-7 Codex 写入沙箱依赖：openEuler 容器内 `workspace-write` 写文件探测定位到 Docker 默认安全策略阻止 `bubblewrap` 创建 namespace；openEuler 运行脚本使用 `--privileged`，preflight 执行真实 `bwrap --ro-bind / / true` 探针；依据：`--privileged` 下 Codex 创建 `hello.txt` 成功。
- [x] Final 封板核验入口：`scripts/final_board_check.py` 逐项检查无密钥测试、真实 E2E、连续成功、Benchmark、Dashboard、Replay、密钥泄漏和证据目录完整性。
- [x] openEuler no-git 约束：Dockerfile 构建阶段只检查 git 二进制存在，不执行 git 命令；`.dockerignore` 排除 `final-evidence/`、`run-data/`、`benchmark/` 和 `.runtime-docker/`。
- [x] Final 证据安全：`final-evidence/` 加入 `.gitignore`，真实日志、截图、录屏和运行证据不提交远程仓库。
- [x] P1-7 Preflight 非交互探针：`scripts/preflight_openeuler.py` 的外部命令统一关闭 stdin，避免 Codex CLI 在 Docker 非 TTY 环境等待额外输入。
- [x] 真实 E2E 挂载仓库兼容：`run_real_direct.py` 与 `run_real_runtime.py` 在执行前将 `--source-repo` 加入 git `safe.directory`，支持 openEuler 容器挂载独立 demo repo。
- [x] Codex 并发隔离：Direct 与 Runtime Codex 子进程使用 attempt 级 `CODEX_HOME` 并复制 `config.toml`，避免并发安装 system skills 时共享 `/root/.codex` 产生竞态。
- [x] Runtime tester direct_tool payload：`tester_node` 向 Runtime 提交 `__tool.name=run_pytest` 和 pytest 参数，满足 `direct_tool` backend 输入契约；依据：openEuler 容器内 `python3 -m pytest testing/unittest/applications/test_tester_business_failure.py testing/unittest/applications/test_incident_execution_provider.py -q`。
- [x] Runtime direct_tool 错误前缀 JSON 解析：Runtime tester 业务失败返回 `[错误] {...}` 时剥离前缀解析 JSON，保留 `returncode != 0` 进入 repair，不再作为结构化解析系统失败；依据：`python3 -m pytest testing/unittest/applications/test_incident_execution_provider.py -q`。
- [x] Runtime backend event trace 归一化：daemon 将 worker 上报的嵌套 `backend_event.event.name` 记录为真实 trace 事件名，Fault 脚本可从 `/runs/<run_id>/events` 捕获 `backend.started` 并触发 SIGKILL；依据：`python3 -m pytest testing/unittest/applications/test_runtime_fault_script.py -q`。
- [x] Runtime Fault run task 发现与 attempt pid 记录：`/runs/<run_id>/tasks` 暴露 root run 下 Runtime task，Fault 脚本用真实 task 事件匹配 `coder_a backend.started`，daemon 对嵌套 backend event 同步写入 attempt `backend_pid`；依据：`python3 -m pytest testing/unittest/applications/test_runtime_fault_script.py -q`。
- [x] Runtime Fault 注入等待边界：Fault 注入协程不再用 Runtime 子摘要 `SUCCESS` 提前退出，而是等待 LangGraph workflow 完成信号，避免 Planner 成功后错过后续 `coder_a backend.started`；依据：`python3 -m pytest testing/unittest/applications/test_runtime_fault_script.py -q`。
- [x] Runtime Fault backend pid 注入兜底：Fault 脚本从 `/runs/<run_id>/tasks` 识别 `coder_a` 任务处于 `RUNNING` 且 attempt 已有 `backend_pid` 时立即 SIGKILL，避免事件轮询窗口错过真实 `backend.started`；依据：`python3 -m pytest testing/unittest/applications/test_runtime_fault_script.py -q`。
- [x] Runtime Fault workflow 线程化：真实 Fault 脚本将同步 LangGraph workflow 放入独立线程执行，避免 provider `wait_task()` 阻塞注入协程，确保 SIGKILL 在 `coder_a` Codex 执行期间触发；依据：`python3 -m pytest testing/unittest/applications/test_runtime_fault_script.py -q`。
- [x] Runtime Fault coder 零重试 fallback：`fault_mode=true` 时 Runtime provider 对 coder/repair 使用 `max_retries=0`，SIGKILL 后直接进入 `coder_b` fallback，避免同一 `coder_a` 重启后等待完整 task timeout；依据：`python3 -m pytest testing/unittest/applications/test_incident_execution_provider.py -q`。
- [x] Runtime Fault 应用层等待 fallback：`fault_mode=true` 的 coder/repair Runtime provider 等待时间覆盖一次失败 attempt 加一次 fallback attempt，避免 daemon 已完成 `coder_b SUCCESS` 但 LangGraph 过早判定 `coder failed`；依据：`python3 -m pytest testing/unittest/applications/test_incident_execution_provider.py -q`。
- [x] Runtime Fault 注入优先 backend_pid：`/debug/faults/workers/{agent_name}/sigkill` 优先杀当前 attempt 的 `backend_pid`，再回退到 worker pid，避免只杀 worker 导致真实 Fault 只能等 task timeout；依据：`python3 -m pytest testing/unittest/applications/test_runtime_fault_script.py -q`。
- [x] Runtime Fault 证据 pair 口径：Fault manifest 的 Task/Attempt/PID/worktree 变化按首个失败 `coder_a` 及同一 task 的 `coder_b` fallback pair 计算，避免多 Coder DAG 稀释 `same_task_id` 判定；依据：`python3 -m pytest testing/unittest/applications/test_runtime_fault_script.py -q`。
- [x] Runtime wait_task 轮询容错：`AgentRuntimeClient.wait_task()` 对 `/tasks/<id>` 轮询中的临时 HTTP 超时继续等待，避免 agentd 任务已完成但 E2E 驱动因单次 ReadTimeout 直接写入 `error=timed out`；依据：`python3 -m pytest testing/unittest/api/test_client.py -q`。
- [x] Coder 无 patch 失败路由：`coder_node` 返回 `workflow_status=FAILED` 时 LangGraph 直接进入 failed，不再继续 integrate/test/review，避免某个 coder 无 patch 后被后续节点掩盖为 `no pending patches to integrate`；依据：`python3 -m pytest testing/unittest/applications/test_incident_graph_runner.py -q`。
- [x] Repair 无 patch 失败路由：`repair_node` 返回 `workflow_status=FAILED` 时 LangGraph 直接进入 failed，不再继续 `integrate_repair`，避免 reviewer 拒绝后的无 patch 修复被覆盖为 `no pending patches to integrate`；依据：`python3 -m pytest testing/unittest/applications/test_incident_graph_runner.py -q`。
- [x] Runtime completed Agent 复用状态同步：复用已完成 Agent 时同步 AgentSpec 与 ACB 到 `READY`，避免下一任务调度触发 `COMPLETED -> RUNNING` 非法转换；依据：openEuler 容器内 `python3 -m pytest testing/unittest/daemon/test_lifecycle.py -q`。
- [x] TODO9 Runtime 真实 E2E：openEuler 容器运行 `scripts/run_real_runtime.py --require-real`，`runtime_real_4c442fe4667a` 返回 `SUCCESS`，pytest 9 passed、Reviewer approved、active leases 为空；证据：`final-evidence/runtime-e2e/runtime_real_4c442fe4667a.log` 与 `run-data/live/runtime_real_4c442fe4667a/summary.json`。
- [x] 真实 E2E 稳定性：`run_real_direct.py` 与 `run_real_runtime.py` 支持 `INCIDENT_REAL_MAX_CONCURRENCY`，默认真实 API 验收并发为 1，降低 Codex 上游流断开概率。
- [x] Codex transient 重试：Direct 与 Runtime Codex 后端对 `stream disconnected before completion` / `Upstream request failed` 执行有限重试，避免瞬时 API 流断开直接终止真实 E2E。
- [x] Direct Codex 结构化输出稳定性：真实 openEuler 探针确认 `codex exec --output-schema` 会触发上游流断开，Direct 模式改为不传 CLI schema，保留最终 JSON 的 Pydantic 校验。
- [x] 真实 E2E 超时可配置：`run_real_direct.py` 与 `run_real_runtime.py` 支持 `INCIDENT_REAL_TASK_TIMEOUT_S`/`INCIDENT_REAL_WORKFLOW_TIMEOUT_S`，避免真实 Codex 长任务被固定 300s 截断；`final_board_check.py` 跳过无权限证据文件，避免 root 生成的 Codex 配置导致核验崩溃。
- [x] Final 密钥扫描范围：`final_board_check.py` 排除 Codex 私有运行目录 `.codex-home`，防止 shell snapshot/config 等 CLI 内部文件造成误报；真实日志、Trace、Dashboard 证据仍参与扫描。
- [x] Patch artifact 过滤：`WorkspaceManager.create_patch_artifact()` 排除 `.codex-home`、`.codex-events.jsonl` 和 `.codex-final.json`，避免真实 Codex 私有文件进入 patch 和后续集成冲突。
- [x] Direct 输出隔离：Direct Codex 的 `CODEX_HOME`、`final.json` 和 `events.jsonl` 已改为写入 artifact 目录，避免污染 worktree；相关单测已补。
- [x] P0-2/P0-3 Coder 拓扑串行执行：应用层增加 coder 依赖校验与确定性选择，Coder 使用最新 integrated commit，Coder/Repair 集成拆分，完成依赖顺序、checkpoint 恢复、私有文件泄漏和集成进度单测；依据：`python3 -m pytest testing/unittest/applications/test_coder_dependency_validation.py testing/unittest/applications/test_coder_selection.py testing/unittest/applications/test_coder_base_commit.py testing/unittest/applications/test_coder_integration_progress.py testing/integration/test_incident_sequential_coders.py -q`。
- [x] P2-11/P2-12/P2-13 真实 E2E 参数化与干净仓库：`run_real_direct.py` / `run_real_runtime.py` 增加 `--max-concurrency`、`--max-repair-rounds`、`--task-timeout-s`、`--workflow-timeout-s`、`--evidence-dir`，每次通过 `scripts/prepare_e2e_repo.py` 生成独立干净 demo repo，并输出合法 JSON manifest；依据：`python3 -m pytest testing/unittest/applications/test_prepare_e2e_repo.py -q`。
- [x] Codex CLI 非交互参数顺序：Direct、Runtime backend 和 preflight 统一使用 `codex --ask-for-approval never exec ...`，避免 `--ask-for-approval` 被 `exec` 子命令误解析；依据：`python3 -m pytest testing/unittest/backends/test_codex_command.py testing/unittest/applications/test_direct_codex.py -q`。
- [x] Direct E2E Codex artifact 目录：Direct executor 在设置 attempt 级 `CODEX_HOME` 前预创建 artifact/codex-home 目录，避免真实 Codex 因目录不存在退出；依据：`python3 -m pytest testing/unittest/applications/test_direct_codex.py -q`。
- [x] Coder 失败态可观测性：Coder 超时/无 patch 不再抛出导致 graph_state 回退初始态，而是返回 `workflow_status=FAILED`、错误和 execution_record，便于真实 E2E 定位；依据：`python3 -m pytest testing/unittest/applications/test_coder_base_commit.py -q`。
- [x] Runtime Planner 失败态可观测性：Runtime provider 结构化输出解析失败返回 FAILED result，Planner 节点保留 runtime task/attempt/execution_record，不再因异常回退初始 graph_state；依据：`python3 -m pytest testing/unittest/applications/test_runtime_provider_parse_failure.py -q`。
- [x] Runtime 真实后端校验：`/metrics` 暴露 agentd LLM 后端与 key 状态，`run_real_runtime.py --require-real` 拒绝 mock backend，结构化解析失败保留输出前缀；同时移除 `configs/runtime.json` 明文 key，真实运行依赖环境变量；依据：`python3 -m pytest testing/unittest/applications/test_runtime_provider_parse_failure.py testing/unittest/applications/test_run_real_runtime_precheck.py -q`。
- [x] Runtime Fault 真实 E2E 入口：新增 `scripts/run_real_runtime_fault.py`，异步启动 Runtime workflow，轮询真实 `/runs/<run_id>/events` 中 coder backend started 事件后注入 `coder_a` SIGKILL，并输出 fault JSON manifest；依据：`python3 -m pytest testing/unittest/applications/test_runtime_fault_script.py -q`。
- [x] Benchmark 正式配对约束：comparison runner 改为 Direct/Runtime 交错配对，`WorkflowMetric`/`RunMetric` 增加 `pair_id`、`pair_index` 和公平性元数据，正式非 smoke 运行默认要求 tracked 工作区干净，`--allow-dirty` 会关闭性能结论；依据：`python3 -m pytest testing/unittest/applications/test_comparison_runner.py testing/unittest/applications/test_comparison_metrics.py -q`。
- [x] Final 深度封板检查：`final_board_check.py` 增加 HEAD 与 `git_commit.txt`、E2E manifest commit、真实 summary、Runtime task/attempt、Fault worker/fallback、Benchmark real/comparable/非零指标校验，并按时间顺序验证最后两次连续成功；依据：`python3 -m pytest testing/unittest/applications/test_final_board_check.py -q`。
- [x] Codex auth 超时根因收敛：`start_agentd_docker.sh` 与测试脚本一致挂载宿主 `${CODEX_HOME:-$HOME/.codex}/config.toml` 到容器 `/root/.codex/config.toml`，Preflight 在 `--require-real` 下缺少 Codex config 立即失败，不再等待 300s；依据：`python3 -m pytest testing/unittest/applications/test_start_agentd_docker.py testing/unittest/applications/test_preflight_codex_config.py -q`。
- [x] Direct 真实入口 Codex config 早失败：`DirectCodexExecutor` 和 `DirectExecutionProvider` 在真实 Codex 配置缺失时直接报错，并在外部 `codex_home` 分支统一复制宿主 `config.toml`，避免同类超时重复出现；依据：`python3 -m pytest testing/unittest/applications/test_direct_codex.py -q`。
- [x] Runtime 取消链路任务追踪：`AgentRuntimeExecutionProvider` 在 provider 内部维护 `run_id -> task_id` 集合，提交后登记、任务结束后清理、`cancel_run()` 逐个取消活跃任务；依据：`python3 -m pytest testing/unittest/applications/test_incident_execution_provider.py -q`。
- [x] Benchmark Runtime Agent 自动注册：正式 Runtime Benchmark 在计时前自动注册 demo agents，校验 agentd 可达、LLM backend 非 mock、agentd 已持有 LLM key、`architect/coder_a/coder_b/tester/repair/reviewer` 均已注册且 backend 与 `agents.yaml` 一致，注册结果写入 `report.json`；依据：`python3 -m pytest testing/unittest/applications/test_comparison_runner.py testing/unittest/applications/test_agent_registration.py -q`。
- [x] Benchmark 实验场景参数：comparison runner 支持 `--experiment baseline|fault-recovery|recovery-context`、`--direct-retry`、`--runtime-fault`、`--recovery-context on|off`，场景字段进入 raw/workflow/trial/report 与公平性校验；Runtime fault 复用 `backend.started` 事件触发 SIGKILL，不使用固定延时；依据：`python3 -m pytest testing/unittest/applications/test_comparison_runner.py -q`。
- [x] TODO7 Direct 连续成功验证：openEuler 真实 Direct E2E 本轮三次均为 `SUCCESS`，run_id 为 `direct_real_2af5e953d8cc`、`direct_real_e9de41091178`、`direct_real_4ce75edff248`，最后两次连续成功；三次 summary 均显示 patch 非空、pytest returncode 0、Reviewer approved true。
- [x] TODO8 真实 agentd 启动验证：`scripts/start_agentd_docker.sh` 启动 openEuler agentd，`final-evidence/environment/agentd_metrics.json` 显示 `llm_backend=deepseek`、`llm_api_key_present=true`、6 个 worker 存活、资源 lease 为空；`agentd_agents.json` 记录 `architect/coder_a/coder_b/tester/repair/reviewer` 均已注册且 backend 与 `agents.yaml` 一致。
- [x] Runtime E2E 空 patch 根因定位与最小修复：失败 run `runtime_real_58af10abafd8` 的 Codex final 输出引用 `/app/examples/production_incident_demo/target_repo`，但 manifest 的 prepared repo 是 `/app/run-data/e2e-repos/runtime_real_58af10abafd8/repo`，说明 Codex 未被固定到 attempt worktree；Runtime Codex prompt 已补 `Goal:` 和 attempt workspace 约束，Coder/Repair prompt 已补 JSON-only 输出契约；依据：`python3 -m pytest testing/unittest/backends/test_codex_command.py -q` 为 `6 passed`。
- [x] Runtime attempt worktree 根因修复：中断验证 run `runtime_real_679998eae8e1` 的 `/tasks/<id>` 显示 `task_input.source_repo=/app/run-data/e2e-repos/.../repo`，但 attempt `workspace_path=/app`，原因是 Runtime Provider 提交任务未传 daemon 已支持的 `workspace` 字段；已补齐 `AgentRuntimeClient.submit_task(..., workspace=...)` 和 Runtime Provider 的 `WorkspaceSpec(source_repo/base_commit/base_ref/read_only)` 传递，避免 daemon 回退到默认 `/app`；依据：`python3 -m pytest testing/unittest/api/test_client.py testing/unittest/applications/test_incident_execution_provider.py testing/unittest/backends/test_codex_command.py -q` 为 `36 passed`。
- [x] Runtime E2E 容器路径共享修复：失败 run `runtime_real_1ee0ae6e5ef9` 显示 Planner 在 agentd 容器内找不到 `/app/run-data/e2e-repos/.../repo`，原因是 E2E 容器准备 repo 后，agentd 容器没有挂载宿主 `run-data` 到同一 `/app/run-data` 路径；`scripts/start_agentd_docker.sh` 已增加 `SHARED_RUN_DATA_DIR:/app/run-data` 挂载；依据：`python3 -m pytest testing/unittest/applications/test_start_agentd_docker.py -q`。
- [x] DeepSeek 模型名修复：失败 run `runtime_real_d8d301297d52` 的 Planner 400 错误显示当前 API 只支持 `deepseek-v4-pro` 或 `deepseek-v4-flash`，而 Runtime 硬编码/配置仍使用 `deepseek-chat`；`LLMGateway` 已改为使用 `LLM_MODEL`/runtime config model，默认与配置更新为 `deepseek-v4-flash`，daemon 启动 worker 时传递 `LLM_MODEL`；依据：`python3 -m pytest testing/unittest/llm/test_gateway.py testing/unittest/daemon/test_worker_service.py -q`。
- [x] Runtime Planner timeout 传递修复：失败 run `runtime_real_7c440d734782` 的 run_config 为 `task_timeout_s=900`，但 Runtime task trace 显示 `task.timeout timeout_s=300.0`；`planner_node` 已去掉 300s 硬裁剪，真实 E2E 参数会传入 Runtime task；依据：openEuler Docker 内 `python3 -m pytest testing/unittest/applications/test_planner_timeout.py testing/unittest/applications/test_incident_execution_provider.py -q` 为 `20 passed`。
- [x] Runtime Planner heartbeat 阻塞修复：失败 run `runtime_real_86186a5efd94` 在 `planner.repo_scan` 后约 10s 出现 `worker.lost heartbeat_stale`，原因是 Planner 在 worker 事件循环内同步调用 DeepSeek；`DirectDeepSeekLLMAdapter.complete()` 已将同步 `chat_with_stats` 放入线程执行，避免阻塞 heartbeat；依据：openEuler Docker 内 `python3 -m pytest testing/unittest/applications/test_shared_planner_pipeline.py testing/unittest/planner/test_native_planner_backend.py testing/unittest/applications/test_planner_timeout.py -q` 为 `5 passed`。
- [x] Runtime Planner schema 兼容修复：失败 run `runtime_real_deab67b6fb43` 显示 DeepSeek 返回 `InspectionRequest.searches` 为字符串数组（如 `JWT`、`authorization`），Pydantic 要求对象数组导致 Planner 失败；`normalize_inspection_payload()` 已将字符串搜索项归一化为 `{query, path}`；依据：openEuler Docker 内 `python3 -m pytest testing/unittest/planner/test_inspection_parser.py testing/unittest/applications/test_shared_planner_pipeline.py testing/unittest/planner/test_native_planner_backend.py -q` 为 `6 passed`。
- [x] Runtime Planner 空 JSON 输出重试：失败 run `runtime_real_4ed672a5b867` 中 native planner 第一次 LLM 输出为空，导致 `Expecting value: line 1 column 1`；`PlannerPipeline` 对 inspection/plan JSON 解析各执行一次重试，第二次仍失败才保留原错误；依据：openEuler Docker 内 `python3 -m pytest testing/unittest/applications/test_shared_planner_pipeline.py testing/unittest/planner/test_native_planner_backend.py testing/unittest/applications/test_incident_execution_provider.py -q` 为 `25 passed`。
- [x] Runtime attempt artifacts patch 提取修复：失败 run `runtime_real_6fd094a4c3c4` 的 daemon 已在 `.runtime-docker/artifacts/runtime_real_6fd094a4c3c4/.../changes.patch` 生成 10473 字节 patch，但应用层只读取 `result.artifacts`，未读取 `attempts[*].artifacts`，导致 `coder produced no patch`；Runtime Provider 已从 attempt artifacts 提取 patch_ref；依据：openEuler Docker 内 `python3 -m pytest testing/unittest/applications/test_incident_execution_provider.py -q` 为 `20 passed`。
- [x] Runtime artifact 容器路径映射修复：失败 run `runtime_real_e07929d7c45b` 已生成 patch_ref 和 12067 字节 patch，但集成阶段在 E2E 驱动容器内找不到 agentd 返回的 `/runtime/artifacts/.../changes.patch`；`PatchIntegrationService` 已将 `/runtime/artifacts` 映射到 host artifact root 后再做 sha256 校验；依据：openEuler Docker 内 `python3 -m pytest testing/unittest/applications/test_patch_integration.py testing/unittest/applications/test_incident_execution_provider.py -q` 为 `22 passed`。
- [x] 真实 E2E 卡住定位与兜底：`IncidentRunService.execute_run()` 使用 `workflow_timeout_s` 包裹 graph 执行，超时后调用 provider `cancel_run()` 并写入 FAILED summary；Docker openEuler 启动脚本增加 `--init` 回收 Codex/bubblewrap 子进程，避免 PID 1 Python 累积僵尸进程；依据：`python3 -m pytest testing/unittest/applications/test_incident_graph_runner.py testing/unittest/applications/test_start_agentd_docker.py -q`。
- [x] 真实 E2E PID1 防误跑：Direct/Runtime/Fault 真实入口启动时拒绝 Python 作为 PID 1 运行，要求 Docker `--init` 或显式 `ALLOW_PYTHON_PID1_E2E=1`，避免再次盲跑出 Codex/bubblewrap 僵尸进程；依据：`python3 -m pytest testing/unittest/applications/test_e2e_runtime_guard.py testing/unittest/applications/test_start_agentd_docker.py -q`。
- [x] 真实 E2E 节点级进度落盘：`IncidentGraphRunner` 改为 LangGraph `astream(stream_mode="updates")`，每个节点完成后写入 `graph_state.json` 并记录 `graph.node.updated`，避免长跑时只能看到 `CREATED` 初始态；依据：`python3 -m pytest testing/unittest/applications/test_incident_graph_runner.py -q`。
- [x] TODO6 Direct 真实 E2E 失败证据持久化：`run_real_direct.py` 在 openEuler 镜像默认 `/runtime/workspaces`、`/runtime/artifacts` 下运行时，改为落到仓库内 `run-data/workspaces`、`run-data/artifacts`，保留 Codex worktree、events、final 和 patch 诊断材料；依据：`python3 -m pytest testing/unittest/applications/test_run_real_direct_paths.py -q`。
- [x] TODO6 Reviewer 失败根因修复：真实 Direct run `direct_real_880020615eae` 证明 Coder、Patch 集成和 Tester 已通过，但 Reviewer 输出 Markdown 导致 `ReviewSummaryModel` JSON 校验失败；已将 Reviewer prompt 改为 JSON-only，并让 `workflow_status=FAILED` 的 review 路由直接进入 failed，避免误入 repair；依据：`python3 -m pytest testing/unittest/applications/test_incident_graph_routing.py -q`。
- [x] TODO6 Direct 真实 E2E：修复后 openEuler 真实 Direct run `direct_real_e658a53d1d0f` 成功，Planner 生成 3 个 Coder 任务，Coder 按依赖串行完成 `fix_auth`、`fix_main`、`fix_orders`，3 个 patch 均非空且无 Codex 私有文件，最终 integrated commit 为 `0cef8f8ebf4e19edc9c3095807730925012a88c2`，Tester `10 passed, 0 failed`，Reviewer 返回结构化 JSON 且 `approved=true`；证据：`final-evidence/direct-e2e/direct_real_e658a53d1d0f.log`、`run-data/live/direct_real_e658a53d1d0f/summary.json`、`run-data/live/direct_real_e658a53d1d0f/graph_state.json`。
- [x] 剩余封板 TODO 清单：删除过时 `progress_2026-07-22.txt`，新增 `remaining_todos_2026-07-24.txt`，记录 TODO7 至 final_board_check 的剩余验收项。
