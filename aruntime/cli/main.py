"""agentctl 命令行工具"""
import typer
import yaml
from rich.console import Console
from aruntime.api.client import AgentRuntimeClient
import time

app = typer.Typer(name="agentctl", help="Agent Runtime 控制工具")
console = Console()
client = AgentRuntimeClient()

def wait_task_done(task_id: str, timeout_s: float = 120.0) -> dict:
    start = time.time()
    while time.time() - start < timeout_s:
        data = client.get_task(task_id)
        if data["status"] in ("SUCCESS", "FAILED"):
            return data
        time.sleep(0.2)
    raise RuntimeError(f"任务未在 {timeout_s}s 内完成: {task_id}")


@app.command()
def submit(workflow_file: str):
    """提交工作流并执行"""
    with open(workflow_file) as f:
        workflow = yaml.safe_load(f)

    console.print(f"[green]加载工作流:[/green] {workflow['workflow']['name']}")

    # 注册 Agent
    for agent in workflow["workflow"]["agents"]:
        client.create_agent(agent["name"], agent["role"])
        console.print(f"  [cyan]注册:[/cyan] {agent['name']} ({agent['role']})")

    flow = workflow["workflow"]["flow"]
    step_task_ids: dict[str, str] = {}
    ordered_steps: list[tuple[str, dict]] = []

    for idx, step in enumerate(flow):
        step_id = str(step.get("id") or f"step_{idx}")
        ordered_steps.append((step_id, step))

        deps = step.get("dependencies", step.get("depends_on", []))
        if deps is None:
            deps = []
        if not isinstance(deps, list):
            raise RuntimeError(f"flow[{idx}].dependencies 必须是 list[str]")
        dep_task_ids = []
        for dep in deps:
            dep_task_id = step_task_ids.get(str(dep))
            if not dep_task_id:
                raise RuntimeError(f"flow[{idx}] 依赖的 step id 不存在或尚未提交: {dep}")
            dep_task_ids.append(dep_task_id)

        name = step["agent"]
        console.print(f"\n[bold]▶ {step_id} ({name})[/bold]")
        resp = client.submit_task(
            name,
            {"request": step.get("input", "")},
            dependencies=dep_task_ids,
        )
        step_task_ids[step_id] = resp["task_id"]

    for step_id, step in ordered_steps:
        task_id = step_task_ids[step_id]
        data = wait_task_done(task_id, timeout_s=120.0)
        if data["status"] == "SUCCESS":
            output = ((data.get("result") or {}).get("output") or "").strip()
            console.print(f"  [green]结果:[/green] {output}")
        else:
            err = (data.get("error") or "").strip()
            console.print(f"  [red]失败:[/red] {err}")

    console.print("\n[bold green]✔ 完成![/bold green]")


@app.command()
def metrics():
    """查看系统指标"""
    m = client.get_metrics()
    console.print(f"Agents: {m['agents']}, Tasks: {m['tasks']}")


if __name__ == "__main__":
    app()
