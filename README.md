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
