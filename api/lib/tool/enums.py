from enum import Enum

class ToolType(str, Enum):
    HTTP = "http"
    MCP = "mcp"
    LOGICAL = "logical"

class AuthType(str, Enum):
    BEARER = "bearer"
    HEADER = "header"