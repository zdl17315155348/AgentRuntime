"""agentd 守护进程 - 接收请求，模拟执行任务"""
import asyncio
import logging
from datetime import datetime
from typing import Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from aruntime.core.models import AgentSpec, TaskSpec, TaskStatus, AgentStatus
from aruntime.core.lifecycle import transition_to, InvalidTransitionError
from aruntime.scheduler.fifo import FIFOScheduler
import os
from aruntime.llm.gateway import LLMGateway

import json

# 配置路径：优先使用环境变量指定的路径，默认从项目根目录的 configs/ 下加载
CONFIG_PATH = os.getenv("RUNTIME_CONFIG", 
    os.path.join(os.path.dirname(__file__), "..", "..", "configs", "runtime.json"))


def load_config():
    """加载 JSON 配置文件"""
    config_path = CONFIG_PATH
    if not os.path.exists(config_path):
        # 如果配置文件不存在，使用默认配置（mock 模式）
        return {
            "llm": {
                "backend": "mock",
                "api_key": "",
                "model": "deepseek-chat",
                "temperature": 0.1,
                "max_tokens": 2048
            }
        }
    with open(config_path, "r") as f:
        return json.load(f)


# 加载配置
config = load_config()
llm_config = config.get("llm", {})

# 初始化 LLM 网关
LLM_BACKEND = os.getenv("LLM_BACKEND", llm_config.get("backend", "deepseek"))
LLM_API_KEY = os.getenv("LLM_API_KEY", llm_config.get("api_key", ""))
llm_gateway = LLMGateway(backend=LLM_BACKEND, api_key=LLM_API_KEY)

scheduler = FIFOScheduler()

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
    if req.agent_name in agents:
        raise HTTPException(status_code=400, detail=f"Agent '{req.agent_name}' 已存在")

    agent = AgentSpec(
        agent_name=req.agent_name,
        role=req.role,
        system_prompt=req.system_prompt,
        model=req.model,
        max_retries=req.max_retries,
    )
    agents[agent.agent_name] = agent
    transition_to(agent, AgentStatus.READY)
    logger.info(f"Agent created: {agent.agent_name} (status: {agent.status})")
    return {"agent_name": agent.agent_name, "status": agent.status}

@app.get("/agents")
async def list_agents():
    return {
        "agents": [            {
                "name": name,
                "role": agent.role,
                "status": agent.status,
                "current_task": agent.current_task_id,
            }
            for name, agent in agents.items()
        ]
    }

@app.post("/tasks")
async def submit_task(req: SubmitTaskRequest):
    if req.agent_name not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{req.agent_name}' 不存在")

    agent = agents[req.agent_name]
    if agent.status not in (AgentStatus.READY, AgentStatus.COMPLETED, AgentStatus.FAILED):
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{req.agent_name}' 当前状态为 {agent.status}，无法接受新任务"
        )

    task = TaskSpec(
        agent_name=req.agent_name,
        task_input=req.task_input,
        context_id=req.context_id,
        priority=req.priority,
    )
    tasks[task.task_id] = task
    scheduler.enqueue(task)
    logger.info(f"任务 {task.task_id} 已入队（等待前面 {scheduler.pending_count - 1} 个任务）")

    return {"task_id": task.task_id, "status": task.status, "message": "任务已加入调度队列"}

@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    t = tasks[task_id]
    return {"task_id": t.task_id, "status": t.status, "result": t.result, "error": t.error}

# ───── 调度循环（后台任务） ─────

async def scheduling_loop():
    """后台不断从队列取任务并执行"""
    while True:
        try:
            task = scheduler.dequeue()
            if task is None:
                await asyncio.sleep(0.5)
                continue

            agent = agents.get(task.agent_name)
            if agent is None:
                task.status = TaskStatus.CANCELLED
                continue

            transition_to(agent, AgentStatus.RUNNING)
            agent.current_task_id = task.task_id
            logger.info(f"调度：任务 {task.task_id} → Agent '{task.agent_name}'")

            system_prompt = agent.system_prompt or f"你是一个{agent.role}"
            user_message = str(task.task_input)

            try:
                output = llm_gateway.chat(system_prompt, user_message)
                task.status = TaskStatus.SUCCESS
                task.result = {"role": agent.role, "output": output}
                transition_to(agent, AgentStatus.COMPLETED)
                logger.info(f"任务 {task.task_id} ✓")
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                transition_to(agent, AgentStatus.FAILED)
                logger.error(f"任务 {task.task_id} ✗: {e}")
                task.result = {"role": agent.role, "output": f"[错误] {str(e)}"}

            task.completed_at = datetime.now()
            agent.current_task_id = None

        except Exception as e:
            logger.error(f"调度循环异常: {e}")
            await asyncio.sleep(1)

@app.on_event("startup")
async def startup():
    asyncio.create_task(scheduling_loop())
    logger.info("调度循环已启动")

@app.get("/metrics")
async def metrics():
    status_counts = {}
    for agent in agents.values():
        s = agent.status.value
        status_counts[s] = status_counts.get(s, 0) + 1

    return {
        "agents": {
            "total": len(agents),
            "by_status": status_counts,
        },
        "tasks": {
            "total": len(tasks),
            "pending": scheduler.pending_count,
            "success": sum(1 for t in tasks.values() if t.status == TaskStatus.SUCCESS),
            "running": sum(1 for t in tasks.values() if t.status == TaskStatus.RUNNING),
            "failed": sum(1 for t in tasks.values() if t.status == TaskStatus.FAILED),
        },
    }

def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8234, log_level="info")

if __name__ == "__main__":
    main()
