from pydantic import BaseModel
from typing import Optional

from lib.tool.enums import AuthType

class CreateMCPToolSet(BaseModel):
    name: str
    description: str
    url: str
    auth_required: Optional[bool] = False
    auth_type: Optional[AuthType] = None
    token: Optional[str] = None
    header: Optional[str] = None
    tools: Optional[list[str]] = None
    shared: Optional[bool] = False

class CreateHttpToolSet(BaseModel):
    name: str
    description: str
    auth_required: Optional[bool] = False
    auth_type: Optional[AuthType] = None
    token: Optional[str] = None
    header: Optional[str] = None
    url: str
    shared: Optional[bool] = False

class SetToolSetCredential(BaseModel):
    token: str

class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict

class ToolsResponse(BaseModel):
    tools: list[ToolDefinition]

class ExecuteHTTPTool(BaseModel):
    tool: str
    arguments: dict