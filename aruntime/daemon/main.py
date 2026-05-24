import asyncio
import logging
from datetime import datetime
from typing import Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from aruntime.core.models import AgentSpec, TaskSpec, TaskStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentd")

agents: Dict[str, AgentSpec] = {}
tasks: Dict[str, TaskSpec] = {}

app = FastAPI(title="Agent Runtime Daemon", version="0.1.0")

class CreateAgentRequest(BaseModel):
    agent_name: str
    role: str
    system_prompt: str = ""
    model: str = "gpt-4o-mini"
    max_retries: int = 3

class SubmitTaskRequest(BaseModel):
    agent_name: str
    task_input: dict
    context_id: str = ""
    priority: int = 0

@app.post("/agents")
async def create_agent(req: CreateAgentRequest):
    agent = AgentSpec(**req.model_dump())
    agents[agent.agent_name] = agent
    logger.info(f"Agent created: {agent.agent_name}")
    return {"agent_name": agent.agent_name, "status": "CREATED"}

@app.get("/agents")
async def list_agents():
    return {"agents": list(agents.keys()), "count": len(agents)}

@app.post("/tasks")
async def submit_task(req: SubmitTaskRequest):
    if req.agent_name not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{req.agent_name}' not found")

    task = TaskSpec(
        agent_name=req.agent_name,
        task_input=req.task_input,
        context_id=req.context_id,
        priority=req.priority,
        status=TaskStatus.RUNNING,
    )
    tasks[task.task_id] = task
    logger.info(f"Task {task.task_id} → {req.agent_name}")

    # 模拟执行：等待 1 秒
    await asyncio.sleep(1)

    task.status = TaskStatus.SUCCESS
    task.result = {
        "role": agents[req.agent_name].role,
        "output": f"[模拟] {req.agent_name} 已完成，输入：{req.task_input}",
    }
    task.completed_at = datetime.now()
    logger.info(f"Task {task.task_id} ✓")

    return {"task_id": task.task_id, "status": task.status, "result": task.result}

@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    t = tasks[task_id]
    return {"task_id": t.task_id, "status": t.status, "result": t.result, "error": t.error}

@app.get("/metrics")
async def metrics():
    return {
        "agents": len(agents),
        "tasks": len(tasks),
        "success": sum(1 for t in tasks.values() if t.status == TaskStatus.SUCCESS),
        "running": sum(1 for t in tasks.values() if t.status == TaskStatus.RUNNING),
        "failed": sum(1 for t in tasks.values() if t.status == TaskStatus.FAILED),
    }

def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8234, log_level="info")

if __name__ == "__main__":
    main()