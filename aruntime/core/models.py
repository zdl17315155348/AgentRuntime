from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from enum import Enum
from datetime import datetime


class AgentStatus(str, Enum):
    """Agent 生命周期状态"""
    CREATED = "CREATED"      # 已创建，未就绪
    READY = "READY"          # 就绪，等待调度
    RUNNING = "RUNNING"      # 正在执行
    WAITING = "WAITING"      # 等待依赖任务完成
    FAILED = "FAILED"        # 执行失败
    COMPLETED = "COMPLETED"  # 执行成功
    KILLED = "KILLED"        # 被终止


class TaskStatus(str, Enum):
    PENDING = "PENDING"      # 等待调度
    READY = "READY"          # 就绪，可执行
    RUNNING = "RUNNING"      # 正在执行
    SUCCESS = "SUCCESS"      # 执行成功
    FAILED = "FAILED"        # 执行失败
    CANCELLED = "CANCELLED"  # 被取消


class TaskSpec(BaseModel):
    task_id: str = Field(default_factory=lambda: f"task_{datetime.now().timestamp()}")
    agent_name: str
    task_input: Dict[str, Any]
    context_id: Optional[str] = None
    priority: int = 0
    dependencies: List[str] = []       # 依赖的任务 ID 列表
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


class AgentSpec(BaseModel):
    agent_name: str
    role: str
    system_prompt: str = ""
    model: str = "gpt-4o-mini"
    status: AgentStatus = AgentStatus.CREATED
    current_task_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    max_retries: int = 3
    memory_max_bytes: Optional[int] = None
    cpu_max: Optional[str] = None
    llm_max_concurrent: int = 1
