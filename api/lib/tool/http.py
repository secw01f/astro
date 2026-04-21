import hashlib
import hmac
import os
import time
import httpx

from typing import Any
from urllib.parse import urlparse
from haystack.core.serialization import generate_qualified_class_name
from haystack.tools import Tool, Toolset
from settings import settings

from lib.tool.models import ExecuteHTTPTool

def _signed_headers(method: str, url: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    parsed = urlparse(url)
    path = parsed.path or "/"
    message = f"{timestamp}:{method.upper()}:{path}".encode("utf-8")
    signature = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-Astro-Timestamp": timestamp,
        "X-Astro-Signature": signature,
    }

class HttpProxyToolset(Toolset):
    """
    Proxies tool calls to a remote HTTP tool server. Stores only URL + JSON specs in
    ``to_dict`` (no pickled callables), matching how Haystack serializes nested agents.
    """

    def __init__(self, base_url: str, tool_specs: list[dict[str, Any]]) -> None:
        self.base_url = base_url.rstrip("/")
        self.tool_specs = list(tool_specs)
        super().__init__(tools=self._build_tools())

    def _build_tools(self) -> list[Tool]:
        tools: list[Tool] = []
        base = self.base_url
        for spec in self.tool_specs:
            remote_name = spec["name"]
            description = spec.get("description") or ""
            parameters = spec.get("parameters")
            if not parameters:
                parameters = {"type": "object", "properties": {}, "required": []}

            def _invoke(
                *,
                _b: str = base,
                _r: str = remote_name,
                **kwargs: Any,
            ) -> Any:
                with httpx.Client(timeout=15.0) as client:
                    payload = ExecuteHTTPTool(tool=_r, arguments=dict(kwargs))
                    exec_url = f"{_b}/exec"
                    response = client.post(
                        exec_url,
                        json=payload.model_dump(),
                        headers=_signed_headers("POST", exec_url),
                    )
                    response.raise_for_status()
                    data = response.json()
                    return data.get("result", data)

            tools.append(
                Tool(
                    name=remote_name,
                    description=description,
                    parameters=parameters,
                    function=_invoke,
                )
            )
        return tools

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": generate_qualified_class_name(type(self)),
            "data": {
                "base_url": self.base_url,
                "tool_specs": [
                    {
                        "name": s["name"],
                        "description": s.get("description") or "",
                        "parameters": s.get("parameters"),
                    }
                    for s in self.tool_specs
                ],
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HttpProxyToolset":
        inner = data["data"]
        return cls(
            base_url=inner["base_url"],
            tool_specs=inner["tool_specs"],
        )

def http_toolset_factory(db_toolset, db_tools) -> HttpProxyToolset:
    specs: list[dict[str, Any]] = []
    for row in db_tools:
        specs.append(
            {
                "name": row.name,
                "description": row.description,
                "parameters": row.input
                if row.input is not None
                else {"type": "object", "properties": {}, "required": []},
            }
        )
    return HttpProxyToolset(base_url=db_toolset.url, tool_specs=specs)

async def get_tools(url) -> dict:
    async with httpx.AsyncClient() as client:
        tools_url = f"{url}/tools"
        r = await client.get(
            tools_url,
            headers=_signed_headers("GET", tools_url),
        )
        r.raise_for_status()
        return r.json()