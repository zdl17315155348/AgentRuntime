# Demo Runbook

## openEuler smoke

```bash
bash scripts/test_docker_openeuler.sh
```

该脚本在 openEuler 容器中构建镜像并执行单元、集成、smoke 和 benchmark 门禁。

## 真实 Direct E2E

```bash
python3 scripts/preflight_openeuler.py --require-real
python3 scripts/run_real_direct.py --require-real
```

要求环境变量只在运行时注入：

```text
DEEPSEEK_API_KEY 或 LLM_API_KEY
OPENAI_API_KEY 或 CODEX_API_KEY
```

输出证据位于 `run-data/live/<run_id>/summary.json` 和 `e2e_evidence.json`。

## 真实 Runtime E2E

先启动 agentd：

```bash
python3 -m aruntime.daemon.main
```

再执行：

```bash
python3 scripts/run_real_runtime.py --require-real
```

Runtime 模式会注册 `examples/production_incident_demo/agents.yaml` 中的 `native_planner`、`codex_cli`、`direct_tool` 后端。

## 故障 Demo

```bash
bash examples/production_incident_demo/scripts/run_fault.sh
```

输出位于 `examples/production_incident_demo/output/latest/`，其中 `trace.json` 包含 `worker.lost` 和 `task.fallback`。
