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
