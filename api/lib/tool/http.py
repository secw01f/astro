import hashlib
import hmac
import json
import secrets
import time
import httpx

from typing import Any
from urllib.parse import urlparse
from haystack.core.serialization import generate_qualified_class_name
from haystack.tools import Tool, Toolset
from settings import settings

from lib.tool.models import ExecuteHTTPTool
from lib.tool.enums import AuthType
from lib.security.network import validate_outbound_url, validate_outbound_url_async


class HttpToolInvoker:
    def __init__(
        self,
        base_url: str,
        remote_name: str,
        auth_required: bool = False,
        auth_type: AuthType | None = None,
        token: str | None = None,
        header: str | None = None,
        user_id: int | None = None,
    ) -> None:
        self.base_url = base_url
        self.remote_name = remote_name
        self.auth_required = auth_required
        self.auth_type = auth_type
        self.token = token
        self.header = header
        self.user_id = user_id

    def __call__(self, **kwargs: Any) -> Any:
        with httpx.Client(timeout=15.0) as client:
            payload = ExecuteHTTPTool(tool=self.remote_name, arguments=dict(kwargs))
            exec_url = f"{self.base_url}/exec"
            validate_outbound_url(exec_url, allow_internal_tools=True)
            body = json.dumps(
                payload.model_dump(),
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            headers = _request_headers(
                "POST",
                exec_url,
                body=body,
                auth_required=self.auth_required,
                auth_type=self.auth_type,
                token=self.token,
                header=self.header,
                user_id=self.user_id,
            )
            headers.setdefault("Content-Type", "application/json")
            response = client.post(
                exec_url,
                content=body,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            result = data.get("result", data)
            error = data.get("error")
            if result is None and error:
                return {"error": error}
            return result


def _default_port(scheme: str) -> int | None:
    if scheme == "http":
        return 80
    if scheme == "https":
        return 443
    return None


def _same_origin(left: str, right: str) -> bool:
    left_parsed = urlparse(left)
    right_parsed = urlparse(right)
    return (
        left_parsed.scheme == right_parsed.scheme
        and left_parsed.hostname == right_parsed.hostname
        and (left_parsed.port or _default_port(left_parsed.scheme))
        == (right_parsed.port or _default_port(right_parsed.scheme))
    )


def _is_internal_tool_url(url: str) -> bool:
    return _same_origin(url, settings.DEFAULT_TOOLS_BASE_URL)


def _body_hash(body: bytes = b"") -> str:
    return hashlib.sha256(body).hexdigest()


def _signed_headers(
    method: str,
    url: str,
    user_id: int | None = None,
    body: bytes = b"",
) -> dict[str, str]:
    timestamp = str(int(time.time()))
    parsed = urlparse(url)
    path = parsed.path or "/"
    body_digest = _body_hash(body)
    user_value = str(user_id) if user_id is not None else ""
    nonce = secrets.token_urlsafe(24)
    message = f"{timestamp}:{method.upper()}:{path}:{body_digest}:{user_value}:{nonce}".encode("utf-8")
    signature = hmac.new(
        settings.TOOLS_HMAC_SECRET.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "X-Astro-Timestamp": timestamp,
        "X-Astro-Signature": signature,
        "X-Astro-Body-SHA256": body_digest,
        "X-Astro-Nonce": nonce,
    }
    if user_id is not None:
        headers["X-Astro-User-Id"] = str(user_id)
    return headers


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
    body: bytes = b"",
    auth_required: bool = False,
    auth_type: AuthType | None = None,
    token: str | None = None,
    header: str | None = None,
    user_id: int | None = None,
) -> dict[str, str]:
    explicit_auth_headers = _auth_headers(
        auth_required=auth_required,
        auth_type=auth_type,
        token=token,
        header=header,
    )
    if explicit_auth_headers:
        return explicit_auth_headers
    if _is_internal_tool_url(url):
        headers = _signed_headers(method, url, user_id=user_id, body=body)
        headers["Content-Type"] = "application/json"
        return headers
    return {}

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
        user_id: int | None = None,
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
        self.user_id = user_id
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
                        user_id=self.user_id,
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
                "token": None,
                "header": self.header,
                "user_id": self.user_id,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HttpProxyToolset":
        inner = data["data"]
        if inner.get("auth_required") and inner.get("token"):
            raise ValueError("Serialized HTTP toolsets must not include plaintext credentials")
        if inner.get("auth_required"):
            raise ValueError("Authenticated HTTP toolsets must be rebuilt from stored credentials")
        return cls(
            base_url=inner["base_url"],
            tool_specs=inner["tool_specs"],
            auth_required=inner.get("auth_required", False),
            auth_type=AuthType(inner["auth_type"]) if inner.get("auth_type") else None,
            token=inner.get("token"),
            header=inner.get("header"),
            user_id=inner.get("user_id"),
        )

def http_toolset_factory(
    db_toolset,
    db_tools,
    token: str | None = None,
    *,
    user_id: int | None = None,
) -> HttpProxyToolset:
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
        user_id=user_id,
    )

async def get_tools(
    url: str,
    auth_required: bool = False,
    auth_type: AuthType | None = None,
    token: str | None = None,
    header: str | None = None,
) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        tools_url = f"{url}/tools"
        await validate_outbound_url_async(tools_url, allow_internal_tools=True)
        r = await client.get(
            tools_url,
            headers=_request_headers(
                "GET",
                tools_url,
                body=b"",
                auth_required=auth_required,
                auth_type=auth_type,
                token=token,
                header=header,
            ),
        )
        r.raise_for_status()
        return r.json()
