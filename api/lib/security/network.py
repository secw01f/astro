import asyncio
import ipaddress
import socket
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException

from settings import settings

def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _same_origin(left: str, right: str) -> bool:
    left_parsed = urlparse(left)
    right_parsed = urlparse(right)
    return (
        left_parsed.scheme == right_parsed.scheme
        and left_parsed.hostname == right_parsed.hostname
        and (left_parsed.port or _default_port(left_parsed.scheme))
        == (right_parsed.port or _default_port(right_parsed.scheme))
    )


@lru_cache(maxsize=1)
def _allowlist() -> tuple[tuple[Any, ...], tuple[str, ...]]:
    networks = []
    hosts = []
    raw = settings.OUTBOUND_ALLOWLIST.replace(",", " ").split()
    for item in raw:
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            hosts.append(item.lower())
    return tuple(networks), tuple(hosts)


def _is_allowed(host: str, addresses: list[str]) -> bool:
    networks, hosts = _allowlist()
    if host.lower() in hosts:
        return True
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address.strip("[]"))
        except ValueError:
            continue
        if any(ip in network for network in networks):
            return True
    return False


def _resolve_host(host: str, port: int) -> list[str]:
    try:
        return [
            info[4][0]
            for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        ]
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail=f"Unable to resolve outbound host: {host}") from exc


def validate_outbound_host(host: str, port: int = 443) -> None:
    normalized = host.strip().strip("[]").lower()
    addresses = _resolve_host(normalized, port)
    if _is_allowed(normalized, addresses):
        return
    for address in addresses:
        try:
            ipaddress.ip_address(address.strip("[]"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Outbound target is invalid") from exc
    raise HTTPException(status_code=400, detail="Outbound target is not allowlisted")


def validate_outbound_url(url: str, *, allow_internal_tools: bool = False) -> None:
    if allow_internal_tools and _same_origin(url, settings.DEFAULT_TOOLS_BASE_URL):
        return

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Only http and https URLs are allowed")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="URL host is required")
    validate_outbound_host(parsed.hostname, parsed.port or _default_port(parsed.scheme))


async def validate_outbound_url_async(url: str, *, allow_internal_tools: bool = False) -> None:
    await asyncio.to_thread(
        validate_outbound_url,
        url,
        allow_internal_tools=allow_internal_tools,
    )
