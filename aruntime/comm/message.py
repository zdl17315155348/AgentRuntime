from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    message_id: str = Field(default_factory=lambda: f"msg_{datetime.now().timestamp()}")
    from_agent: str
    to_agent: str
    payload: dict[str, Any]
    topic: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)

