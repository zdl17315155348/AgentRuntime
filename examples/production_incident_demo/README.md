# Production Incident Demo

真实 FastAPI 订单服务缺陷修复演示。

运行：

```bash
bash examples/production_incident_demo/scripts/run_normal.sh
bash examples/production_incident_demo/scripts/run_fault.sh
```

输出目录：

```text
examples/production_incident_demo/output/latest/
```

验收文件：`task_dag.json`、`trace.json`、`metrics.json`、`final.patch`、`final_report.md`、`pytest.xml`。
