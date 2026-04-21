from enum import Enum

class ToolType(str, Enum):
    HTTP = "http"
    MCP = "mcp"

class AuthType(str, Enum):
    BEARER = "bearer"
    HEADER = "header"