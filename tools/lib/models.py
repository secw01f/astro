from pydantic import BaseModel
from dataclasses import dataclass
from typing import Callable, Type, List, Any, Optional, Dict

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

class ToolInputSchemaProperty(BaseModel):
    title: Optional[str] = None
    type: str
    default: Optional[Any] = None

class ToolInputSchema(BaseModel):
    properties: Dict[str, ToolInputSchemaProperty]
    required: List[str] = []
    title: Optional[str] = None
    type: str = "object"

class Tool(BaseModel):
    name: str
    description: str
    input_schema: ToolInputSchema

class ToolsResponse(BaseModel):
    tools: List[Tool]

class ExecTool(BaseModel):
    tool: str
    arguments: Dict[str, Any]

class ExecResponse(BaseModel):
    result: Any
    error: str | None = None