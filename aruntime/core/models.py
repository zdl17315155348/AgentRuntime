from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Dict, Any, List, Literal, ClassVar
from enum import Enum
from datetime import datetime
from uuid import uuid4


class AgentStatus(str, Enum):
    """Agent 生命周期状态"""
    CREATED = "CREATED"      # 已创建，未就绪
    READY = "READY"          # 就绪，等待调度
    RUNNING = "RUNNING"      # 正在执行
    WAITING = "WAITING"      # 等待依赖任务完成
    FAILED = "FAILED"        # 执行失败
    COMPLETED = "COMPLETED"  # 执行成功
    SUSPENDED = "SUSPENDED"  # 已暂停
    ISOLATED = "ISOLATED"    # 已隔离
    RECOVERING = "RECOVERING"  # 恢复中
    LOST = "LOST"            # 心跳丢失
    KILLED = "KILLED"        # 被终止


class TaskStatus(str, Enum):
    PENDING = "PENDING"      # 等待调度
    READY = "READY"          # 就绪，可执行
    RUNNING = "RUNNING"      # 正在执行
    BLOCKED = "BLOCKED"      # 等待资源
    ORPHANED = "ORPHANED"    # daemon 恢复时发现原执行者已失联
    TIMEOUT = "TIMEOUT"      # 执行超时
    RETRYING = "RETRYING"    # 正在重试
    FALLBACK = "FALLBACK"    # 正在切换 Agent
    SUCCESS = "SUCCESS"      # 执行成功
    FAILED = "FAILED"        # 执行失败
    CANCELLED = "CANCELLED"  # 被取消


class SideEffectLevel(str, Enum):
    NONE = "none"
    FILE_WRITE = "file_write"
    NETWORK = "network"
    EXTERNAL_API = "external_api"


class AgentBackendType(str, Enum):
    NATIVE_PLANNER = "native_planner"
    CODEX_CLI = "codex_cli"
    DIRECT_TOOL = "direct_tool"
    LEGACY_LLM = "legacy_llm"


class AgentBackendConfig(BaseModel):
    type: AgentBackendType = AgentBackendType.LEGACY_LLM
    model: Optional[str] = None
    executable: str = "codex"
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "read-only"
    approval_policy: Literal["never", "on-request", "untrusted"] = "never"
    timeout_s: int = 300
    ephemeral: bool = True
    output_schema: Optional[str] = None
    max_inspection_files: int = 6
    max_inspection_rounds: int = 1

    @model_validator(mode="after")
    def validate_backend(self):
        if self.type == AgentBackendType.CODEX_CLI and self.sandbox == "danger-full-access":
            raise ValueError("danger-full-access is disabled by default")
        return self


class WorkspaceSpec(BaseModel):
    source_repo: str
    base_ref: str = "HEAD"
    base_commit: Optional[str] = None
    workspace_id: Optional[str] = None
    workspace_path: Optional[str] = None
    read_only: bool = False
    retain_on_failure: bool = True


class ArtifactReference(BaseModel):
    artifact_id: str
    artifact_type: Literal["patch", "test_report", "review", "plan", "log"]
    path: str
    sha256: str
    size_bytes: int
    task_id: str
    attempt_id: str
    created_at: datetime = Field(default_factory=datetime.now)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentCapability(BaseModel):
    can_plan: bool = False
    can_code: bool = False
    can_test: bool = False
    can_review: bool = False
    tools: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    cost_level: int = 1
    reliability_score: float = 1.0


class FailureMode(str, Enum):
    RETRY = "retry"
    FALLBACK = "fallback"
    DEGRADE = "degrade"
    FAIL_OPEN = "fail_open"
    FAIL_CLOSED = "fail_closed"


class FailurePolicy(BaseModel):
    RETRY: ClassVar[str] = "retry"
    FALLBACK: ClassVar[str] = "fallback"
    DEGRADE: ClassVar[str] = "degrade"
    FAIL_OPEN: ClassVar[str] = "fail_open"
    FAIL_CLOSED: ClassVar[str] = "fail_closed"
    ISOLATE: ClassVar[str] = "fail_open"

    mode: Literal["fail_open", "fail_closed", "retry", "fallback", "degrade"] = "fail_open"
    max_retries: int = 0
    fallback_agent: Optional[str] = None
    timeout_ms: int = 120000

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, value):
        if isinstance(value, FailureMode):
            return value.value
        if isinstance(value, str):
            normalized = value.replace("-", "_")
            if normalized == "isolate":
                return "fail_open"
            return normalized
        return value

    @classmethod
    def from_legacy(cls, value) -> "FailurePolicy":
        if isinstance(value, FailurePolicy):
            return value
        if isinstance(value, dict):
            return cls(**value)
        if isinstance(value, str) or isinstance(value, FailureMode):
            return cls(mode=value)
        return cls()


class TaskDefinition(BaseModel):
    agent_name: Optional[str] = None
    task_input: Dict[str, Any]
    dependencies: List[str] = Field(default_factory=list)
    priority: int = 0
    resource_request: Dict[str, Any] = Field(default_factory=dict)


class TaskQueueInfo(BaseModel):
    scheduler_decision_reason: str = ""
    resource_block_reason: str = ""
    queue_wait_ms: Optional[float] = None


class TaskAttempt(BaseModel):
    attempt_id: str
    worker_pid: Optional[int] = None
    agent_name: str
    status: str = "RUNNING"
    failure_reason: str = ""
    token_usage: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    backend_type: str = ""
    backend_session_id: Optional[str] = None
    backend_run_id: Optional[str] = None
    backend_pid: Optional[int] = None
    workspace_id: Optional[str] = None
    workspace_path: Optional[str] = None
    base_commit: Optional[str] = None
    resumed_from_attempt: Optional[str] = None
    recovery_context_id: Optional[str] = None
    exit_code: Optional[int] = None
    artifacts: List[ArtifactReference] = Field(default_factory=list)


class TaskControlBlock(BaseModel):
    task_id: str
    state: TaskStatus = TaskStatus.PENDING
    queue_info: TaskQueueInfo = Field(default_factory=TaskQueueInfo)
    resource_lease: Optional[Dict[str, Any]] = None
    trace_id: str = Field(default_factory=lambda: f"trace_{uuid4().hex}")
    current_attempt: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    agent_runtime_ms: Optional[float] = None

    _ALLOWED: ClassVar[dict[TaskStatus, set[TaskStatus]]] = {
        TaskStatus.PENDING: {TaskStatus.READY, TaskStatus.BLOCKED, TaskStatus.FAILED, TaskStatus.CANCELLED},
        TaskStatus.READY: {TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.FAILED, TaskStatus.CANCELLED},
        TaskStatus.RUNNING: {
            TaskStatus.PENDING,
            TaskStatus.ORPHANED,
            TaskStatus.TIMEOUT,
            TaskStatus.RETRYING,
            TaskStatus.FALLBACK,
            TaskStatus.SUCCESS,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.BLOCKED: {TaskStatus.PENDING, TaskStatus.READY, TaskStatus.FAILED, TaskStatus.CANCELLED},
        TaskStatus.ORPHANED: {TaskStatus.READY, TaskStatus.RETRYING, TaskStatus.FAILED, TaskStatus.CANCELLED},
        TaskStatus.TIMEOUT: {TaskStatus.RETRYING, TaskStatus.FALLBACK, TaskStatus.FAILED, TaskStatus.CANCELLED},
        TaskStatus.RETRYING: {TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED},
        TaskStatus.FALLBACK: {TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED},
        TaskStatus.SUCCESS: set(),
        TaskStatus.FAILED: {TaskStatus.READY},
        TaskStatus.CANCELLED: set(),
    }

    def transition_to(self, state: TaskStatus, reason: str = "") -> None:
        state = TaskStatus(state)
        if state != self.state and state not in self._ALLOWED.get(self.state, set()):
            raise ValueError(f"invalid task transition: {self.state} -> {state}")
        now = datetime.now()
        self.state = state
        if state == TaskStatus.RUNNING and self.started_at is None:
            self.started_at = now
            self.queue_info.queue_wait_ms = round((now - self.created_at).total_seconds() * 1000, 3)
        if state in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TIMEOUT):
            self.completed_at = now
            started = self.started_at or self.created_at
            self.agent_runtime_ms = round((now - started).total_seconds() * 1000, 3)
        if reason:
            self.queue_info.scheduler_decision_reason = reason

    def block(self, reason: str) -> None:
        self.transition_to(TaskStatus.BLOCKED, "resource_blocked")
        self.queue_info.resource_block_reason = reason

    def unblock(self, reason: str = "dependencies_satisfied") -> None:
        self.queue_info.resource_block_reason = ""
        self.transition_to(TaskStatus.READY, reason)


class TaskSpec(BaseModel):
    task_id: str = Field(default_factory=lambda: f"task_{uuid4().hex}")
    agent_name: Optional[str] = None
    task_input: Dict[str, Any]
    context_id: Optional[str] = None
    priority: int = 0
    deadline: Optional[datetime] = None
    resource_request: Dict[str, Any] = Field(default_factory=dict)
    resource_usage: Dict[str, Any] = Field(default_factory=dict)
    resource_lease: Optional[Dict[str, Any]] = None
    token_budget: Optional[int] = None
    timeout: Optional[float] = None
    timeout_ms: Optional[int] = None
    parent_task_id: Optional[str] = None
    root_task_id: Optional[str] = None
    task_role: Optional[str] = None
    required_backend: Optional[AgentBackendType] = None
    workspace: Optional[WorkspaceSpec] = None
    children: List[str] = Field(default_factory=list)
    trace_id: str = Field(default_factory=lambda: f"trace_{uuid4().hex}")
    dependencies: List[str] = Field(default_factory=list)       # 依赖的任务 ID 列表
    dependency_failure_policies: Dict[str, FailureMode] = Field(default_factory=dict)
    failure_policy: FailurePolicy = Field(default_factory=FailurePolicy)
    required_capability: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None
    side_effect_level: SideEffectLevel = SideEffectLevel.NONE
    compensation: Dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    llm_usage: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    queue_wait_ms: Optional[float] = None
    scheduler_decision_reason: str = ""
    resource_block_reason: str = ""
    agent_runtime_ms: Optional[float] = None
    definition: Optional[TaskDefinition] = None
    tcb: Optional[TaskControlBlock] = None
    attempts: List[TaskAttempt] = Field(default_factory=list)

    def model_post_init(self, __context) -> None:
        if self.root_task_id is None:
            self.root_task_id = self.task_id
        if self.definition is None:
            self.definition = TaskDefinition(
                agent_name=self.agent_name,
                task_input=self.task_input,
                dependencies=list(self.dependencies),
                priority=self.priority,
                resource_request=dict(self.resource_request),
            )
        if self.tcb is None:
            self.tcb = TaskControlBlock(
                task_id=self.task_id,
                state=self.status,
                trace_id=self.trace_id,
                created_at=self.created_at,
                started_at=self.started_at,
                completed_at=self.completed_at,
                resource_lease=self.resource_lease,
                agent_runtime_ms=self.agent_runtime_ms,
                queue_info=TaskQueueInfo(
                    scheduler_decision_reason=self.scheduler_decision_reason,
                    resource_block_reason=self.resource_block_reason,
                    queue_wait_ms=self.queue_wait_ms,
                ),
            )
        self._sync_from_tcb()

    def transition_to(self, status: TaskStatus, reason: str = "") -> None:
        if self.tcb is None:
            self.model_post_init(None)
        self.tcb.transition_to(status, reason)
        self._sync_from_tcb()

    def block(self, reason: str) -> None:
        if self.tcb is None:
            self.model_post_init(None)
        self.tcb.block(reason)
        self._sync_from_tcb()

    def unblock(self, reason: str = "dependencies_satisfied") -> None:
        if self.tcb is None:
            self.model_post_init(None)
        self.tcb.unblock(reason)
        self._sync_from_tcb()

    def set_resource_lease(self, lease: Dict[str, Any] | None) -> None:
        if self.tcb is None:
            self.model_post_init(None)
        self.tcb.resource_lease = lease
        self.resource_lease = lease

    def create_attempt(self, agent_name: str, worker_pid: int | None = None) -> TaskAttempt:
        if self.tcb is None:
            self.model_post_init(None)
        self.tcb.current_attempt += 1
        attempt = TaskAttempt(
            attempt_id=f"{self.task_id}:attempt:{self.tcb.current_attempt}",
            worker_pid=worker_pid,
            agent_name=agent_name,
            backend_type=self.required_backend.value if self.required_backend else "",
            workspace_id=self.workspace.workspace_id if self.workspace else None,
            workspace_path=self.workspace.workspace_path if self.workspace else None,
            base_commit=self.workspace.base_commit if self.workspace else None,
        )
        self.attempts.append(attempt)
        return attempt

    @property
    def active_attempt(self) -> TaskAttempt | None:
        for attempt in reversed(self.attempts):
            if attempt.completed_at is None:
                return attempt
        return None

    def finish_attempt(
        self,
        attempt: TaskAttempt,
        result: Dict[str, Any] | None = None,
        failure_reason: str = "",
        token_usage: Dict[str, Any] | None = None,
    ) -> None:
        attempt.completed_at = datetime.now()
        attempt.result = result
        attempt.failure_reason = failure_reason
        attempt.token_usage = token_usage or {}
        attempt.status = "FAILED" if failure_reason else "SUCCESS"

    def _sync_from_tcb(self) -> None:
        if self.tcb is None:
            return
        self.status = self.tcb.state
        self.trace_id = self.tcb.trace_id
        self.created_at = self.tcb.created_at
        self.started_at = self.tcb.started_at
        self.completed_at = self.tcb.completed_at
        self.resource_lease = self.tcb.resource_lease
        self.agent_runtime_ms = self.tcb.agent_runtime_ms
        self.queue_wait_ms = self.tcb.queue_info.queue_wait_ms
        self.scheduler_decision_reason = self.tcb.queue_info.scheduler_decision_reason
        self.resource_block_reason = self.tcb.queue_info.resource_block_reason

    @field_validator("failure_policy", mode="before")
    @classmethod
    def normalize_failure_policy(cls, value):
        return FailurePolicy.from_legacy(value)

    @field_validator("dependency_failure_policies", mode="before")
    @classmethod
    def normalize_dependency_failure_policies(cls, value):
        if not value:
            return {}
        return {
            str(dep_id): FailureMode(mode.value if isinstance(mode, FailureMode) else str(mode).replace("-", "_"))
            for dep_id, mode in dict(value).items()
        }

    @field_validator("side_effect_level", mode="before")
    @classmethod
    def normalize_side_effect_level(cls, value):
        if isinstance(value, SideEffectLevel):
            return value
        return SideEffectLevel(value or SideEffectLevel.NONE)


class AgentSpec(BaseModel):
    agent_name: str
    role: str
    system_prompt: str = ""
    model: str = "gpt-4o-mini"
    capability: AgentCapability = Field(default_factory=AgentCapability)
    backend: AgentBackendConfig = Field(default_factory=AgentBackendConfig)
    failure_policy: FailurePolicy = Field(default_factory=FailurePolicy)
    status: AgentStatus = AgentStatus.CREATED
    current_task_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    max_retries: int = 3
    restart_budget: int = 3
    fault_domain: Optional[str] = None
    memory_max_bytes: Optional[int] = None
    memory_high_bytes: Optional[int] = None
    cpu_max: Optional[str] = None
    pids_max: Optional[int] = None
    llm_max_concurrent: int = 1
    token_quota: Optional[int] = None
