from __future__ import annotations

from pydantic import BaseModel, Field
import nmap

from lib.tool import create_tool_registry

Registry, tool = create_tool_registry("recon")


class NmapInput(BaseModel):
    targets: list[str] = Field(default_factory=list)
    arguments: list[str] | None = None


@tool(name="nmap", description="Nmap scan that returns structured JSON", capabilities=["port_scan"], version="1.0")
async def nmap_scan(input: NmapInput) -> dict:
    if not input.targets:
        return {"error": "No targets provided", "results": []}

    scanner = nmap.PortScanner()
    targets = " ".join(input.targets)
    arguments = " ".join(input.arguments or [])
    scanner.scan(hosts=targets, arguments=arguments)

    results: list[dict] = []
    for host in scanner.all_hosts():
        host_data = scanner[host]
        host_result: dict = {
            "host": host,
            "status": host_data.state(),
            "hostnames": host_data.get("hostnames", []),
            "addresses": host_data.get("addresses", {}),
            "protocols": {},
        }

        for proto in host_data.all_protocols():
            protocol_ports: list[dict] = []
            for port in sorted(host_data[proto].keys()):
                service = host_data[proto][port]
                protocol_ports.append(
                    {
                        "port": port,
                        "state": service.get("state"),
                        "reason": service.get("reason"),
                        "name": service.get("name"),
                        "product": service.get("product"),
                        "version": service.get("version"),
                        "extrainfo": service.get("extrainfo"),
                        "cpe": service.get("cpe"),
                    }
                )
            host_result["protocols"][proto] = protocol_ports

        results.append(host_result)

    return {
        "targets": input.targets,
        "arguments": input.arguments or [],
        "scanner": scanner.scaninfo(),
        "stats": scanner.scanstats(),
        "results": results,
    }