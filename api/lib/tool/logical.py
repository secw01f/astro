from __future__ import annotations

from lib.tool.enums import ToolType
from src.db.models import Tool, ToolSet

def toolset_catalog_tools(toolset: ToolSet) -> list[Tool]:
    if toolset.type == ToolType.LOGICAL:
        return list(toolset.member_tools or [])
    return list(toolset.tools or [])

def compound_toolsets(toolsets: list[ToolSet]) -> list[ToolSet]:
    seen: dict[int, ToolSet] = {}
    for toolset in toolsets:
        if toolset.id is None:
            continue
        if toolset.type == ToolType.LOGICAL:
            for tool in toolset.member_tools or []:
                parent = tool.toolset
                if parent is not None and parent.id is not None:
                    seen[parent.id] = parent
        elif toolset.type in (ToolType.HTTP, ToolType.MCP):
            seen[toolset.id] = toolset
    return list(seen.values())

def dedupe_tools(tools: list[Tool]) -> list[Tool]:
    seen: dict[int, Tool] = {}
    for tool in tools:
        if tool.id is not None:
            seen[tool.id] = tool
    return list(seen.values())
