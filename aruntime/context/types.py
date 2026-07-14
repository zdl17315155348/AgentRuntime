from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ContextPermission(str, Enum):
    SHARED = "shared"
    PRIVATE = "private"
    READONLY = "readonly"


class ContextObject(BaseModel):
    key: str
    value: Any
    owner_agent: str | None = None
    permission: ContextPermission
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
