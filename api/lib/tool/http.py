import hashlib
import hmac
import time
import httpx

from typing import Any
from urllib.parse import urlparse
from haystack.core.serialization import generate_qualified_class_name
from haystack.tools import Tool, Toolset
from settings import settings

from lib.tool.models import ExecuteHTTPTool
from lib.tool.enums import AuthType


class HttpToolInvoker:
    def __init__(
        self,
        base_url: str,
        remote_name: str,
        auth_required: bool = False,
        auth_type: AuthType | None = None,
        token: str | None = None,
        header: str | None = None,
    ) -> None:
        self.base_url = base_url
        self.remote_name = remote_name
        self.auth_required = auth_required
        self.auth_type = auth_type
        self.token = token
        self.header = header

    def __call__(self, **kwargs: Any) -> Any:
        with httpx.Client(timeout=15.0) as client:
            payload = ExecuteHTTPTool(tool=self.remote_name, arguments=dict(kwargs))
            exec_url = f"{self.base_url}/exec"
            response = client.post(
                exec_url,
                json=payload.model_dump(),
                headers=_request_headers(
                    "POST",
                    exec_url,
                    auth_required=self.auth_required,
                    auth_type=self.auth_type,
                    token=self.token,
                    header=self.header,
                ),
            )
            response.raise_for_status()
            data = response.json()
            result = data.get("result", data)
            error = data.get("error")
            if result is None and error:
                return {"error": error}
            return result


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


def _auth_headers(
    auth_required: bool = False,
    auth_type: AuthType | None = None,
    token: str | None = None,
    header: str | None = None,
) -> dict[str, str]:
    if not auth_required:
        return {}
    if not token:
        return {}
    if auth_type == AuthType.HEADER and header:
        return {header: token}
    normalized = token.strip()
    if normalized.lower().startswith("bearer "):
        return {"Authorization": normalized}
    return {"Authorization": f"Bearer {normalized}"}


def _request_headers(
    method: str,
    url: str,
    auth_required: bool = False,
    auth_type: AuthType | None = None,
    token: str | None = None,
    header: str | None = None,
) -> dict[str, str]:
    explicit_auth_headers = _auth_headers(
        auth_required=auth_required,
        auth_type=auth_type,
        token=token,
        header=header,
    )
    if explicit_auth_headers:
        return explicit_auth_headers
    return _signed_headers(method, url)

class HttpProxyToolset(Toolset):
    """
    Proxies tool calls to a remote HTTP tool server. Stores only URL + JSON specs in
    ``to_dict`` (no pickled callables), matching how Haystack serializes nested agents.
    """

    def __init__(
        self,
        base_url: str,
        tool_specs: list[dict[str, Any]],
        auth_required: bool = False,
        auth_type: AuthType | None = None,
        token: str | None = None,
        header: str | None = None,
    ) -> None:
        if auth_required and not token:
            raise ValueError("Authenticated HTTP toolsets require a credential token at initialization")
        if auth_required and auth_type == AuthType.HEADER and not header:
            raise ValueError("Authenticated HTTP toolsets with header auth require a header name")

        self.base_url = base_url.rstrip("/")
        self.tool_specs = list(tool_specs)
        self.auth_required = auth_required
        self.auth_type = auth_type
        self.token = token
        self.header = header
        super().__init__(tools=self._build_tools())

    def _build_tools(self) -> list[Tool]:
        tools: list[Tool] = []
        for spec in self.tool_specs:
            remote_name = spec["name"]
            description = (spec.get("description") or "").strip() or f"Execute the {remote_name} tool."
            parameters = spec.get("parameters")
            if not parameters:
                parameters = {"type": "object", "properties": {}, "required": []}

            tools.append(
                Tool(
                    name=remote_name,
                    description=description,
                    parameters=parameters,
                    function=HttpToolInvoker(
                        base_url=self.base_url,
                        remote_name=remote_name,
                        auth_required=self.auth_required,
                        auth_type=self.auth_type,
                        token=self.token,
                        header=self.header,
                    ),
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
                "auth_required": self.auth_required,
                "auth_type": self.auth_type.value if self.auth_type else None,
                "token": self.token,
                "header": self.header,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HttpProxyToolset":
        inner = data["data"]
        return cls(
            base_url=inner["base_url"],
            tool_specs=inner["tool_specs"],
            auth_required=inner.get("auth_required", False),
            auth_type=AuthType(inner["auth_type"]) if inner.get("auth_type") else None,
            token=inner.get("token"),
            header=inner.get("header"),
        )

def http_toolset_factory(db_toolset, db_tools, token: str | None = None) -> HttpProxyToolset:
    if db_toolset.auth_required and not token:
        raise ValueError(f"Toolset {db_toolset.id} requires credentials but no token was provided")

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
    return HttpProxyToolset(
        base_url=db_toolset.url,
        tool_specs=specs,
        auth_required=db_toolset.auth_required,
        auth_type=db_toolset.auth_type,
        token=token,
        header=getattr(db_toolset, "header", None),
    )

async def get_tools(
    url: str,
    auth_required: bool = False,
    auth_type: AuthType | None = None,
    token: str | None = None,
    header: str | None = None,
) -> dict:
    async with httpx.AsyncClient() as client:
        tools_url = f"{url}/tools"
        r = await client.get(
            tools_url,
            headers=_request_headers(
                "GET",
                tools_url,
                auth_required=auth_required,
                auth_type=auth_type,
                token=token,
                header=header,
            ),
        )
        r.raise_for_status()
        return r.json()