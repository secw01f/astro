from pydantic import BaseModel
from typing import Optional

class CreateMCPToolSet(BaseModel):
    name: str
    description: str
    url: str
    tools: Optional[list[str]] = None

class CreateHttpToolSet(BaseModel):
    name: str
    description: str
    url: str

class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict

class ToolsResponse(BaseModel):
    tools: list[ToolDefinition]

class ExecuteHTTPTool(BaseModel):
    tool: str
    arguments: dict