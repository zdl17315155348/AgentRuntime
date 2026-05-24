"""agentctl 命令行工具"""
import typer
import yaml
from rich.console import Console
from aruntime.api.client import AgentRuntimeClient

app = typer.Typer(name="agentctl", help="Agent Runtime 控制工具")
console = Console()
client = AgentRuntimeClient()


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

    # 顺序执行
    for step in workflow["workflow"]["flow"]:
        name = step["agent"]
        console.print(f"\n[bold]▶ {name}[/bold]")
        result = client.submit_task(name, {"request": step.get("input", "")})
        console.print(f"  [green]结果:[/green] {result['result']['output']}")

    console.print("\n[bold green]✔ 完成![/bold green]")


@app.command()
def metrics():
    """查看系统指标"""
    m = client.get_metrics()
    console.print(f"Agents: {m['agents']}, Tasks: {m['tasks']}, "
                  f"Success: {m['success']}, Failed: {m['failed']}")


if __name__ == "__main__":
    app()