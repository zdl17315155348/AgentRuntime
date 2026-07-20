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
