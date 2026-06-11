"""agentd 守护进程 - 接收请求，模拟执行任务"""
import asyncio
import logging
from datetime import datetime
from typing import Dict
import subprocess
import sys

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from aruntime.core.models import AgentSpec, TaskSpec, TaskStatus, AgentStatus
from aruntime.core.lifecycle import transition_to, InvalidTransitionError
from aruntime.scheduler.fifo import FIFOScheduler
from aruntime.scheduler.dag import DAGScheduler
from aruntime.scheduler.base import BaseScheduler
import os
from aruntime.llm.gateway import LLMGateway
from aruntime.comm.message import Message
from aruntime.comm.router import MessageRouter
from aruntime.comm.transport import start_uds_server
from aruntime.resource.cgroup import apply_cgroup_v2
from aruntime.resource.monitor import ResourceMonitor
from aruntime.scheduler.resource_aware import ResourceAwareScheduler

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
scheduler_config = config.get("scheduler", {})

# 初始化 LLM 网关
LLM_BACKEND = os.getenv("LLM_BACKEND", llm_config.get("backend", "deepseek"))
LLM_API_KEY = os.getenv("LLM_API_KEY", llm_config.get("api_key", ""))
llm_gateway = LLMGateway(backend=LLM_BACKEND, api_key=LLM_API_KEY)

agents: Dict[str, AgentSpec] = {}
tasks: Dict[str, TaskSpec] = {}

# 初始化调度器
SCHEDULER_TYPE = os.getenv("SCHEDULER_TYPE", scheduler_config.get("type", "fifo"))
resource_aware = os.getenv("RESOURCE_AWARE", "").lower() in ("true", "1", "yes") or scheduler_config.get("resource_aware", False)
resource_monitor: ResourceMonitor | None = None

if SCHEDULER_TYPE == "dag":
    _inner: BaseScheduler = DAGScheduler()
else:
    _inner: BaseScheduler = FIFOScheduler()

if resource_aware:
    resource_monitor = ResourceMonitor()
    scheduler: BaseScheduler = ResourceAwareScheduler(_inner, resource_monitor, agents)
else:
    scheduler: BaseScheduler = _inner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentd")

agent_inflight_tasks: Dict[str, int] = {}
message_router = MessageRouter()
uds_server = None
agent_workers: Dict[str, subprocess.Popen] = {}
pending_task_results: Dict[str, asyncio.Future] = {}

app = FastAPI(title="Agent Runtime Daemon", version="0.1.0")

def _start_worker(agent_name: str) -> subprocess.Popen:
    uds_path = os.getenv("AGENTD_UDS_PATH", "/tmp/agent-runtime-agentd.sock")
    env = os.environ.copy()
    env["AGENT_NAME"] = agent_name
    env["AGENTD_UDS_PATH"] = uds_path
    env["LLM_BACKEND"] = llm_gateway.backend
    env["LLM_API_KEY"] = llm_gateway.api_key or ""
    proc = subprocess.Popen(
        [sys.executable, "-m", "aruntime.worker.agent_worker"],
        cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    agent_workers[agent_name] = proc
    agent = agents.get(agent_name)
    if agent is not None:
        cg = apply_cgroup_v2(
            pid=proc.pid,
            group_name=agent_name,
            memory_max_bytes=agent.memory_max_bytes,
            cpu_max=agent.cpu_max,
        )
        if cg.get("ok") is not True and cg.get("error"):
            logger.info(f"cgroup 未生效: {cg.get('error')}")
    return proc


def _stop_worker(agent_name: str) -> None:
    proc = agent_workers.get(agent_name)
    if proc is None:
        return
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    agent_workers.pop(agent_name, None)


class CreateAgentRequest(BaseModel):
    agent_name: str
    role: str
    system_prompt: str = ""
    model: str = "gpt-4o-mini"
    max_retries: int = 3
    memory_max_bytes: int | None = None
    cpu_max: str = ""

class SubmitTaskRequest(BaseModel):
    agent_name: str
    task_input: dict
    context_id: str = ""
    priority: int = 0
    dependencies: list[str] = []


class SubmitDynamicTaskRequest(BaseModel):
    agent_name: str
    task_input: dict
    parent_task_id: str = ""
    context_id: str = ""
    priority: int = 0


class SendMessageRequest(BaseModel):
    from_agent: str
    to_agent: str
    payload: dict
    topic: str = ""

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
        memory_max_bytes=req.memory_max_bytes,
        cpu_max=req.cpu_max or None,
    )
    agents[agent.agent_name] = agent
    transition_to(agent, AgentStatus.READY)
    _start_worker(agent.agent_name)
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
                "worker_pid": (agent_workers.get(name).pid if name in agent_workers else None),
            }
            for name, agent in agents.items()
        ]
    }


@app.post("/agents/{agent_name}/kill")
async def kill_agent(agent_name: str):
    if agent_name not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")
    _stop_worker(agent_name)
    agent = agents[agent_name]
    if agent.status != AgentStatus.KILLED:
        try:
            transition_to(agent, AgentStatus.KILLED)
        except Exception:
            agent.status = AgentStatus.KILLED
    agent_inflight_tasks[agent_name] = 0
    return {"agent_name": agent_name, "status": agent.status}


@app.post("/agents/{agent_name}/restart")
async def restart_agent(agent_name: str):
    if agent_name not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")
    agent = agents[agent_name]
    if agent.status == AgentStatus.KILLED:
        raise HTTPException(status_code=409, detail=f"Agent '{agent_name}' 已 KILLED")
    _stop_worker(agent_name)
    _start_worker(agent_name)
    if agent.status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.WAITING):
        transition_to(agent, AgentStatus.READY)
    return {"agent_name": agent_name, "status": agent.status}

@app.post("/tasks")
async def submit_task(req: SubmitTaskRequest):
    if req.agent_name not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{req.agent_name}' 不存在")

    agent = agents[req.agent_name]
    if agent_inflight_tasks.get(req.agent_name, 0) > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{req.agent_name}' 当前已有未完成任务，无法接受新任务",
        )
    if agent.status not in (AgentStatus.READY, AgentStatus.COMPLETED, AgentStatus.FAILED):
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{req.agent_name}' 当前状态为 {agent.status}，无法接受新任务"
        )
    if agent.status in (AgentStatus.COMPLETED, AgentStatus.FAILED):
        transition_to(agent, AgentStatus.READY)

    # 验证依赖任务是否存在
    for dep_id in req.dependencies:
        if dep_id not in tasks:
            raise HTTPException(status_code=404, detail=f"依赖任务 '{dep_id}' 不存在")

    task = TaskSpec(
        agent_name=req.agent_name,
        task_input=req.task_input,
        context_id=req.context_id,
        priority=req.priority,
        dependencies=req.dependencies,
    )
    tasks[task.task_id] = task
    scheduler.enqueue(task)
    agent_inflight_tasks[req.agent_name] = agent_inflight_tasks.get(req.agent_name, 0) + 1
    logger.info(f"任务 {task.task_id} 已入队（依赖: {req.dependencies}，等待前面 {scheduler.pending_count - 1} 个任务）")

    return {"task_id": task.task_id, "status": task.status, "message": "任务已加入调度队列"}


@app.post("/tasks/dynamic")
async def submit_dynamic_task(req: SubmitDynamicTaskRequest):
    """
    动态提交任务（由运行中的任务生成）
    """
    if req.agent_name not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{req.agent_name}' 不存在")

    if agent_inflight_tasks.get(req.agent_name, 0) > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{req.agent_name}' 当前已有未完成任务，无法接受新任务",
        )
    agent = agents[req.agent_name]
    if agent.status in (AgentStatus.COMPLETED, AgentStatus.FAILED):
        transition_to(agent, AgentStatus.READY)
    
    # 验证父任务是否存在
    if req.parent_task_id and req.parent_task_id not in tasks:
        raise HTTPException(status_code=404, detail=f"父任务 '{req.parent_task_id}' 不存在")

    task = TaskSpec(
        agent_name=req.agent_name,
        task_input=req.task_input,
        context_id=req.context_id,
        priority=req.priority,
        dependencies=[req.parent_task_id] if req.parent_task_id else [],
    )
    tasks[task.task_id] = task
    
    # 如果是 DAG 调度器，使用 add_dynamic_task
    if hasattr(scheduler, 'add_dynamic_task'):
        scheduler.add_dynamic_task(task, req.parent_task_id)
    else:
        scheduler.enqueue(task)
    agent_inflight_tasks[req.agent_name] = agent_inflight_tasks.get(req.agent_name, 0) + 1
    
    logger.info(f"动态任务 {task.task_id} 已入队（父任务: {req.parent_task_id}）")
    return {"task_id": task.task_id, "status": task.status, "message": "动态任务已加入调度队列"}

@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    t = tasks[task_id]
    return {"task_id": t.task_id, "status": t.status, "result": t.result, "error": t.error}


@app.post("/messages")
async def send_message(req: SendMessageRequest):
    if req.from_agent not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{req.from_agent}' 不存在")
    if req.to_agent not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{req.to_agent}' 不存在")

    msg = Message(
        from_agent=req.from_agent,
        to_agent=req.to_agent,
        payload=req.payload,
        topic=req.topic or None,
    )
    await message_router.route(msg)
    return msg.model_dump()


@app.get("/messages/{agent_name}")
async def receive_messages(agent_name: str, limit: int = 50):
    if agent_name not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    messages = message_router.receive(agent_name, limit=limit)
    return {"messages": [m.model_dump() for m in messages]}

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
                agent_inflight_tasks[task.agent_name] = max(agent_inflight_tasks.get(task.agent_name, 0) - 1, 0)
                continue

            if agent.status in (AgentStatus.COMPLETED, AgentStatus.FAILED):
                transition_to(agent, AgentStatus.READY)
            transition_to(agent, AgentStatus.RUNNING)
            agent.current_task_id = task.task_id
            logger.info(f"调度：任务 {task.task_id} → Agent '{task.agent_name}'")

            system_prompt = agent.system_prompt or f"你是一个{agent.role}"
            user_message = str(task.task_input)

            acquired = False

            try:
                max_attempts = int(getattr(agent, "max_retries", 1) or 1)
                if max_attempts < 1:
                    max_attempts = 1

                last_error = ""
                success_output = None

                for attempt in range(max_attempts):
                    loop = asyncio.get_running_loop()
                    fut = loop.create_future()
                    pending_task_results[task.task_id] = fut
                    try:
                        ok = await message_router.wait_connected(task.agent_name, timeout_s=5.0)
                        if not ok:
                            proc = agent_workers.get(task.agent_name)
                            if proc is not None and proc.poll() is not None:
                                _stop_worker(task.agent_name)
                                _start_worker(task.agent_name)
                                ok = await message_router.wait_connected(task.agent_name, timeout_s=5.0)
                            if not ok:
                                raise RuntimeError("agent worker not connected")

                        # 申请 LLM 资源
                        if resource_aware and resource_monitor is not None:
                            if not resource_monitor.acquire_llm(task.agent_name, agent.llm_max_concurrent):
                                raise RuntimeError("LLM resource not available")
                            acquired = True

                        sent = await message_router.send_event(task.agent_name, {
                            "type": "exec_task",
                            "task_id": task.task_id,
                            "system_prompt": system_prompt,
                            "user_message": user_message,
                            "task_input": task.task_input,
                        })
                        if not sent:
                            raise RuntimeError("failed to send exec_task")

                        try:
                            result = await asyncio.wait_for(fut, timeout=120.0)
                        except asyncio.TimeoutError:
                            raise RuntimeError("task timeout")

                        status = result.get("status")
                        output = result.get("output") or ""
                        error = result.get("error") or ""
                        if status == "SUCCESS":
                            success_output = output
                            break
                        raise RuntimeError(error or "worker error")
                    except Exception as e:
                        last_error = str(e)
                        _stop_worker(task.agent_name)
                        _start_worker(task.agent_name)
                        if attempt < max_attempts - 1:
                            await asyncio.sleep(0.2 * (attempt + 1))
                    finally:
                        pending_task_results.pop(task.task_id, None)

                if success_output is not None:
                    task.status = TaskStatus.SUCCESS
                    task.result = {"role": agent.role, "output": success_output}
                    transition_to(agent, AgentStatus.COMPLETED)
                    scheduler.complete_task(task.task_id)
                    logger.info(f"任务 {task.task_id} ✓")
                else:
                    task.status = TaskStatus.FAILED
                    task.error = last_error or "worker error"
                    transition_to(agent, AgentStatus.FAILED)
                    scheduler.fail_task(task.task_id)
                    logger.error(f"任务 {task.task_id} ✗: {task.error}")
                    task.result = {"role": agent.role, "output": f"[错误] {task.error}"}
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                transition_to(agent, AgentStatus.FAILED)
                scheduler.fail_task(task.task_id)
                logger.error(f"任务 {task.task_id} ✗: {e}")
                task.result = {"role": agent.role, "output": f"[错误] {str(e)}"}
            finally:
                if resource_aware and acquired and resource_monitor is not None:
                    resource_monitor.release_llm(task.agent_name)
                agent_inflight_tasks[task.agent_name] = max(agent_inflight_tasks.get(task.agent_name, 0) - 1, 0)

            task.completed_at = datetime.now()
            agent.current_task_id = None

        except Exception as e:
            logger.error(f"调度循环异常: {e}")
            await asyncio.sleep(1)

@app.on_event("startup")
async def startup():
    asyncio.create_task(scheduling_loop())
    logger.info("调度循环已启动")
    global uds_server
    uds_path = os.getenv("AGENTD_UDS_PATH", "/tmp/agent-runtime-agentd.sock")
    try:
        async def _on_task_result(agent_name: str, data: dict) -> None:
            task_id = str(data.get("task_id") or "").strip()
            if not task_id:
                return
            fut = pending_task_results.get(task_id)
            if fut is None or fut.done():
                return
            fut.set_result({
                "agent_name": agent_name,
                "task_id": task_id,
                "status": data.get("status"),
                "output": data.get("output"),
                "error": data.get("error"),
            })

        uds_server = await start_uds_server(uds_path, message_router, task_result_handler=_on_task_result)
    except Exception as e:
        logger.error(f"UDS server 启动失败: {e}")

    async def worker_monitor_loop():
        while True:
            try:
                for name, agent in list(agents.items()):
                    if agent.status == AgentStatus.KILLED:
                        continue
                    proc = agent_workers.get(name)
                    if proc is None:
                        continue
                    if proc.poll() is not None:
                        _stop_worker(name)
                        _start_worker(name)
            except Exception:
                pass
            await asyncio.sleep(1.0)

    asyncio.create_task(worker_monitor_loop())


@app.on_event("shutdown")
async def shutdown():
    global uds_server
    if uds_server is None:
        pass
    else:
        uds_server.close()
        try:
            await uds_server.wait_closed()
        except Exception:
            pass
        uds_server = None
    for proc in list(agent_workers.values()):
        try:
            proc.terminate()
        except Exception:
            pass
    for name in list(agent_workers.keys()):
        _stop_worker(name)

@app.get("/metrics")
async def metrics():
    status_counts = {}
    for agent in agents.values():
        s = agent.status.value
        status_counts[s] = status_counts.get(s, 0) + 1

    result = {
        "agents": {
            "total": len(agents),
            "by_status": status_counts,
        },
        "workers": {
            "total": len(agent_workers),
            "alive": sum(1 for p in agent_workers.values() if p.poll() is None),
            "dead": sum(1 for p in agent_workers.values() if p.poll() is not None),
        },
        "tasks": {
            "total": len(tasks),
            "pending": scheduler.pending_count,
            "success": sum(1 for t in tasks.values() if t.status == TaskStatus.SUCCESS),
            "running": sum(1 for t in tasks.values() if t.status == TaskStatus.RUNNING),
            "failed": sum(1 for t in tasks.values() if t.status == TaskStatus.FAILED),
        },
    }

    if resource_aware and resource_monitor is not None:
        result["resource"] = resource_monitor.get_snapshot()

    return result

def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8234, log_level="info")

if __name__ == "__main__":
    main()
