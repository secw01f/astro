from pydantic import BaseModel
from typing import Optional

class CreateStack(BaseModel):
    name: str
    description: str
    supervisor: int
    supporting: list[int]

class ExecuteStack(BaseModel):
    message: str

class UpdateStack(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    supervisor: Optional[int] = None
    supporting: Optional[list[int]] = None