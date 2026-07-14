"""
Agent 生命周期管理
定义 Agent 的状态转换规则
"""

from aruntime.core.models import AgentStatus

# 合法的状态转换映射表
# 格式：当前状态 → 允许转换到的下一个状态集合
ALLOWED_TRANSITIONS = {
    AgentStatus.CREATED:   {AgentStatus.READY, AgentStatus.FAILED},
    AgentStatus.READY:     {AgentStatus.RUNNING, AgentStatus.SUSPENDED, AgentStatus.LOST, AgentStatus.KILLED},
    AgentStatus.RUNNING:   {AgentStatus.WAITING, AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.ISOLATED, AgentStatus.LOST, AgentStatus.KILLED},
    AgentStatus.WAITING:   {AgentStatus.READY, AgentStatus.FAILED, AgentStatus.LOST, AgentStatus.KILLED},
    AgentStatus.FAILED:    {AgentStatus.RECOVERING, AgentStatus.ISOLATED, AgentStatus.KILLED},   # 失败后需先进入恢复态
    AgentStatus.LOST:      {AgentStatus.RECOVERING, AgentStatus.ISOLATED, AgentStatus.KILLED},
    AgentStatus.RECOVERING: {AgentStatus.READY, AgentStatus.KILLED},
    AgentStatus.COMPLETED: set(),
    AgentStatus.SUSPENDED: {AgentStatus.READY, AgentStatus.KILLED},
    AgentStatus.ISOLATED:  {AgentStatus.READY, AgentStatus.KILLED},
    AgentStatus.KILLED:    set(),        # 终态，不可转换
}

class InvalidTransitionError(Exception):
    """不合法的状态转换异常"""
    pass

def transition_to(
    agent,
    new_status: AgentStatus,
    task_id: str | None = None,
    reason: str = "",
    detail: dict | None = None,
) -> None:
    """
    将 Agent 转换到新状态
    如果转换不合法，抛出 InvalidTransitionError
    
    参数:
        agent: AgentSpec 对象
        new_status: 目标状态
    """
    current = agent.status
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    
    if new_status not in allowed:
        raise InvalidTransitionError(
            f"Agent '{agent.agent_name}' 不能从 {current} 转换到 {new_status}"
            f"（允许的目标: {[s.value for s in allowed]}）"
        )
    
    if hasattr(agent, "record_transition"):
        agent.record_transition(current, new_status, task_id=task_id, reason=reason, detail=detail)

    agent.status = new_status
    from datetime import datetime
    if hasattr(agent, "updated_at"):
        agent.updated_at = datetime.now()

def can_transition_to(agent, new_status: AgentStatus) -> bool:
    """检查是否能转换到目标状态（不执行转换）"""
    return new_status in ALLOWED_TRANSITIONS.get(agent.status, set())
