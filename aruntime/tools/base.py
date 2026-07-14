from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from aruntime.core.models import SideEffectLevel


class ToolError(RuntimeError):
    pass


class ToolPermissionError(ToolError):
    pass


class ToolTimeoutError(ToolError):
    pass


class ToolSideEffect(str, Enum):
    NONE = SideEffectLevel.NONE.value
    FILE_WRITE = SideEffectLevel.FILE_WRITE.value
    NETWORK = SideEffectLevel.NETWORK.value
    EXTERNAL_API = SideEffectLevel.EXTERNAL_API.value


@dataclass(slots=True)
class ToolExecutionContext:
    workspace_root: Path
    allowed_roots: list[Path] = field(default_factory=list)
    allowed_shell_commands: set[str] = field(default_factory=set)
    timeout_s: float = 30.0
    max_output_bytes: int = 64 * 1024
    allow_network: bool = False
    trace: list[dict[str, Any]] = field(default_factory=list)

    def resolve_path(self, raw_path: str) -> Path:
        candidate = (self.workspace_root / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
        roots = [self.workspace_root.resolve(), *[root.resolve() for root in self.allowed_roots]]
        if not any(candidate == root or root in candidate.parents for root in roots):
            raise ToolPermissionError(f"path outside workspace: {raw_path}")
        return candidate


@dataclass(slots=True)
class ToolResult:
    ok: bool
    output: Any = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    name: str
    side_effect_level: ToolSideEffect

    async def execute(self, arguments: dict[str, Any], execution_context: ToolExecutionContext) -> ToolResult:
        ...
