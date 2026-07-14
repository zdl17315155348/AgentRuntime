from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class Message(BaseModel):
    message_id: str = Field(default_factory=lambda: f"msg_{uuid4().hex}")
    from_agent: str
    to_agent: str
    type: str = "message"
    payload: dict[str, Any]
    trace_id: str = ""
    task_id: Optional[str] = None
    ack_required: bool = True
    topic: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
