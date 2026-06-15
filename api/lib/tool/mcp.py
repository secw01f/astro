import httpx
import logging

from haystack_integrations.tools.mcp import MCPToolset, StreamableHttpServerInfo
from haystack.utils import Secret

from lib.tool.enums import AuthType
from lib.security.network import validate_outbound_url

logger = logging.getLogger(__name__)

def _normalize_bearer_token(token: str) -> str:
    normalized = token.strip()
    if normalized.lower().startswith("bearer "):
        return normalized[7:].strip()
    return normalized

def MCP(server: str, tools: list[str] | None = None, auth_required: bool = False, auth_type: AuthType | None = None, token: str | None = None, header: str | None = None) -> MCPToolset:
    validate_outbound_url(server)
    server_info = StreamableHttpServerInfo(url=server)
    if auth_required:
        if auth_type == AuthType.BEARER:
            if not token:
                raise ValueError("MCP toolset requires a bearer token when auth is enabled")
            server_info.token = Secret.from_token(_normalize_bearer_token(token))
        elif auth_type == AuthType.HEADER:
            if not token or not header:
                raise ValueError("MCP toolset requires both a header name and token when header auth is enabled")
            server_info.header =  {header: Secret.from_token(token)}
    if not tools:
        return MCPToolset(server_info=server_info)
    return MCPToolset(server_info=server_info, tool_names=tools)

def is_valid_server(url: str, auth_required: bool = False, auth_type: AuthType | None = None, token: str | None = None, header: str | None = None) -> bool:
    try:
        validate_outbound_url(url)
        with httpx.Client(timeout=5.0) as client:
            client.headers["Accept"] = "application/json, text/event-stream"
            if auth_required:
                if auth_type == AuthType.BEARER:
                    if not token:
                        logger.error("MCP validation failed: auth is required but no bearer token was provided")
                        return False
                    client.headers["Authorization"] = f"Bearer {_normalize_bearer_token(token)}"
                elif auth_type == AuthType.HEADER:
                    if not token or not header:
                        logger.error("MCP validation failed: header auth requires both a header name and token")
                        return False
                    client.headers[header] = token
            body = {
                "jsonrpc": "2.0",
                "method": "mcp.describe",
                "params": {
                    "tool": "mcp.describe"
                }
            }
            response = client.post(url, json=body)
            if 200 <= response.status_code < 300:
                return True
            logger.error(f"Server is not valid: {response.status_code} {response.text[:200]}")
    except Exception as e:
        logger.error(f"Error checking if server is valid: {e}")
        return False
    return False
