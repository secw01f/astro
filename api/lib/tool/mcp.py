import httpx

from haystack_integrations.tools.mcp import MCPToolset, StreamableHttpServerInfo
from haystack.utils import Secret

from lib.tool.enums import AuthType

def MCP(server: str, tools: list[str] | None = None, auth_required: bool = False, auth_type: AuthType | None = None, token: str | None = None, header: str | None = None) -> MCPToolset:
    server_info = StreamableHttpServerInfo(url=server)
    if auth_required:
        if auth_type == AuthType.BEARER:
            server_info.token = Secret.from_token(token)
        elif auth_type == AuthType.HEADER:
            server_info.header =  {header: Secret.from_token(token)}
    if not tools:
        return MCPToolset(server_info=server_info)
    return MCPToolset(server_info=server_info, tool_names=tools)

def is_valid_server(url: str) -> bool:
    try:
        with httpx.Client() as client:
            body = {
                "jsonrpc": "2.0",
                "method": "mcp.describe",
                "params": {
                    "tool": "mcp.describe"
                }
            }
            response = client.post(url, json=body)
            if response.status_code == 200 and response.json()["result"] is not None:
                return True
            return False
    except Exception as e:
        return False