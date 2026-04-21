import httpx

from haystack_integrations.tools.mcp import MCPToolset, SSEServerInfo

def MCP(server: str, tools: list[str] | None = None) -> MCPToolset:
    server_info = SSEServerInfo(url=server)
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