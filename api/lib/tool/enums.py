from enum import Enum

class ToolType(str, Enum):
    HTTP = "http"
    MCP = "mcp"