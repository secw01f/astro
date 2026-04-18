from haystack_integrations.tools.mcp import MCPToolset, SSEServerInfo

class MCP:
    def __init__(self, server: str, tools: list[str] = None):
        self._mcp_server = SSEServerInfo(url=server)
        self._tools = tools
        
        if not tools:
            toolset = MCPToolset(server_info = self._mcp_server)
        else:
            toolset = MCPToolset(
                server_info = self._mcp_server,
                tool_names = self._tools
            )
        
        return toolset