from typing import Any

import httpx
from haystack.core.serialization import generate_qualified_class_name
from haystack.tools import Tool, Toolset

from lib.tool.models import ExecuteHTTPTool

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
                    response = client.post(
                        f"{_b}/exec",
                        json=payload.model_dump(),
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
        r = await client.get((url + "/tools"))
        r.raise_for_status()
        return r.json()