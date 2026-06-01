from __future__ import annotations

from typing import Any

def unique_tool_catalog(toolsets: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    catalog: dict[int, dict[str, Any]] = {}
    for toolset in toolsets:
        toolset_name = toolset.get("name", "?")
        for tool in toolset.get("tools") or []:
            tool_id = tool["id"]
            if tool_id not in catalog:
                catalog[tool_id] = {"tool": tool, "toolset_names": [toolset_name]}
            elif toolset_name not in catalog[tool_id]["toolset_names"]:
                catalog[tool_id]["toolset_names"].append(toolset_name)
    return catalog

def tool_ids_from_toolsets(toolsets: list[dict[str, Any]], toolset_ids: list[int]) -> set[int]:
    by_id = {toolset["id"]: toolset for toolset in toolsets}
    covered: set[int] = set()
    for toolset_id in toolset_ids:
        toolset = by_id.get(toolset_id)
        if not toolset:
            continue
        for tool in toolset.get("tools") or []:
            covered.add(tool["id"])
    return covered

def tool_choices_from_toolsets(
    toolsets: list[dict[str, Any]],
    *,
    exclude_ids: set[int] | None = None,
) -> list[tuple[int, str]]:
    exclude = exclude_ids or set()
    choices: list[tuple[int, str]] = []
    for tool_id, entry in sorted(unique_tool_catalog(toolsets).items()):
        if tool_id in exclude:
            continue
        tool = entry["tool"]
        names = ", ".join(entry["toolset_names"])
        choices.append((tool_id, f"{tool['name']} ({names})"))
    return choices

def prune_redundant_tool_ids(
    toolsets: list[dict[str, Any]],
    toolset_ids: list[int],
    tool_ids: list[int],
) -> tuple[list[int], list[int]]:
    covered = tool_ids_from_toolsets(toolsets, toolset_ids)
    kept = [tool_id for tool_id in tool_ids if tool_id not in covered]
    removed = [tool_id for tool_id in tool_ids if tool_id in covered]
    return kept, removed

def format_toolset_summary(toolset: dict[str, Any]) -> str:
    toolset_type = toolset.get("type", "?")
    tool_count = len(toolset.get("tools") or [])
    return f"{toolset['id']}: {toolset['name']} ({toolset_type}, {tool_count} tools)"

def format_toolsets(toolsets: list[dict[str, Any]]) -> str:
    if not toolsets:
        return "(none)"
    return ", ".join(format_toolset_summary(toolset) for toolset in toolsets)

def effective_tools(agent: dict[str, Any]) -> dict[int, str]:
    names: dict[int, str] = {}
    for toolset in agent.get("toolsets") or []:
        for tool in toolset.get("tools") or []:
            names[tool["id"]] = tool["name"]
    for tool in agent.get("tools") or []:
        names[tool["id"]] = tool["name"]
    return names

def format_effective_tools(agent: dict[str, Any]) -> str:
    tools = effective_tools(agent)
    if not tools:
        return "(none)"
    return ", ".join(f"{tool_id}: {name}" for tool_id, name in sorted(tools.items()))

def format_additional_tools(agent: dict[str, Any]) -> str:
    covered = set()
    for toolset in agent.get("toolsets") or []:
        for tool in toolset.get("tools") or []:
            covered.add(tool["id"])
    extra = [tool for tool in agent.get("tools") or [] if tool["id"] not in covered]
    if not extra:
        return "(none)"
    return ", ".join(f"{tool['id']}: {tool['name']}" for tool in extra)

def format_tool_list_entry(tool_id: int, entry: dict[str, Any]) -> str:
    tool = entry["tool"]
    names = ", ".join(entry["toolset_names"])
    return f"{tool_id}: {tool['name']} ({names})"

def build_agent_tooling_preview(
    catalog_toolsets: list[dict[str, Any]],
    toolset_ids: list[int],
    tool_ids: list[int],
) -> dict[str, Any]:
    selected_toolsets = [ts for ts in catalog_toolsets if ts["id"] in toolset_ids]
    catalog = unique_tool_catalog(catalog_toolsets)
    extra_tools = [
        catalog[tool_id]["tool"] if tool_id in catalog else {"id": tool_id, "name": str(tool_id)}
        for tool_id in tool_ids
    ]
    return {"toolsets": selected_toolsets, "tools": extra_tools}
