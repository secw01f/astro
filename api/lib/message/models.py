from pydantic import BaseModel
from typing import List, Optional

from src.db.models import MessagePublic

class MessageHistory(BaseModel):
    stack_id: int
    limit: Optional[int] = 50
    offset: Optional[int] = None
    last_position: Optional[int] = None

class MessageHistoryResponse(BaseModel):
    messages: List[MessagePublic]
    total: int
    last_position: int
    more: bool