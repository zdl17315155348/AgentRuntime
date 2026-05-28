"""
Agent 生命周期管理
定义 Agent 的状态转换规则
"""

from aruntime.core.models import AgentStatus

# 合法的状态转换映射表
# 格式：当前状态 → 允许转换到的下一个状态集合
ALLOWED_TRANSITIONS = {
    AgentStatus.CREATED:   {AgentStatus.READY, AgentStatus.KILLED},
    AgentStatus.READY:     {AgentStatus.RUNNING, AgentStatus.KILLED},
    AgentStatus.RUNNING:   {AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.WAITING, AgentStatus.KILLED},
    AgentStatus.WAITING:   {AgentStatus.READY, AgentStatus.KILLED},
    AgentStatus.FAILED:    {AgentStatus.READY, AgentStatus.KILLED},   # 失败后可重试回到 READY
    AgentStatus.COMPLETED: set(),        # 终态，不可转换
    AgentStatus.KILLED:    set(),        # 终态，不可转换
}

class InvalidTransitionError(Exception):
    """不合法的状态转换异常"""
    pass

def transition_to(agent, new_status: AgentStatus) -> None:
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
    
    agent.status = new_status
    from datetime import datetime
    agent.updated_at = datetime.now()

def can_transition_to(agent, new_status: AgentStatus) -> bool:
    """检查是否能转换到目标状态（不执行转换）"""
    return new_status in ALLOWED_TRANSITIONS.get(agent.status, set())