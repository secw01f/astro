import ipaddress
import os
import socket
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


@lru_cache(maxsize=1)
def _allowlist() -> tuple[tuple[Any, ...], tuple[str, ...]]:
    networks = []
    hosts = []
    raw = os.getenv("OUTBOUND_ALLOWLIST", "").replace(",", " ").split()
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
    return [
        info[4][0]
        for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ]


def block_reason_for_host(host: str, port: int = 443) -> str | None:
    normalized = host.strip().strip("[]").lower()
    try:
        addresses = _resolve_host(normalized, port)
    except socket.gaierror:
        return "Execution Blocked"
    if _is_allowed(normalized, addresses):
        return None
    for address in addresses:
        try:
            ipaddress.ip_address(address.strip("[]"))
        except ValueError:
            return "Execution Blocked"
    return "Execution Blocked"


def block_reason_for_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "Only http and https URLs are allowed"
    if not parsed.hostname:
        return "URL host is required"
    return block_reason_for_host(parsed.hostname, parsed.port or _default_port(parsed.scheme))
