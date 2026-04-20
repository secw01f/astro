from pydantic import BaseModel
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Type

@dataclass
class ToolDef:
    name: str
    description: str
    namespace: str
    func: Callable
    input: Type[BaseModel]
    output: Type[BaseModel] | None = None
    capabilities: list[str] = None
    version: str = "0.1"


class Tool(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]

class ToolsResponse(BaseModel):
    tools: List[Tool]

class ExecTool(BaseModel):
    tool: str
    arguments: Dict[str, Any]

class ExecResponse(BaseModel):
    result: Any
    error: str | None = None