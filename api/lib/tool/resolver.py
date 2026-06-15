from __future__ import annotations

import logging
import asyncio
from typing import Any

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from lib.tool.enums import ToolType
from lib.tool.logical import toolset_catalog_tools
from lib.tool.mcp import MCP, is_valid_server
from lib.tool.http import http_toolset_factory
from lib.tool.access import get_user_toolset_token, can_read_toolset, toolset_visibility_filter
from src.db.models import Agent, Tool, ToolSet

logger = logging.getLogger(__name__)

def collect_tools_by_toolset(agent: Agent) -> dict[int, dict[int, Tool]]:
    selected: dict[int, dict[int, Tool]] = {}

    for toolset in agent.toolsets or []:
        if toolset.type == ToolType.LOGICAL:
            for tool in toolset.member_tools or []:
                if tool.toolset_id is None or tool.id is None:
                    continue
                selected.setdefault(tool.toolset_id, {})[tool.id] = tool
            continue
        if toolset.id is None:
            continue
        bucket = selected.setdefault(toolset.id, {})
        for tool in toolset_catalog_tools(toolset):
            if tool.id is not None:
                bucket[tool.id] = tool

    for tool in agent.tools or []:
        if tool.toolset_id is None or tool.id is None:
            continue
        selected.setdefault(tool.toolset_id, {})[tool.id] = tool

    return selected

def _toolsets_by_id(agent: Agent) -> dict[int, ToolSet]:
    by_id: dict[int, ToolSet] = {}
    for toolset in agent.toolsets or []:
        if toolset.type == ToolType.LOGICAL:
            for tool in toolset.member_tools or []:
                parent = tool.toolset
                if parent is not None and parent.id is not None:
                    by_id[parent.id] = parent
            continue
        if toolset.id is not None:
            by_id[toolset.id] = toolset
    for tool in agent.tools or []:
        if tool.toolset_id is not None and tool.toolset is not None:
            by_id.setdefault(tool.toolset_id, tool.toolset)
    return by_id

async def build_agent_toolset_catalog(
    session: AsyncSession,
    agent: Agent,
    user_id: int,
) -> list[Any]:
    selected = collect_tools_by_toolset(agent)
    if not selected:
        return []

    toolsets_by_id = _toolsets_by_id(agent)
    missing_ids = set(selected.keys()) - set(toolsets_by_id.keys())
    if missing_ids:
        stmt = select(ToolSet).where(
            ToolSet.id.in_(missing_ids),
            toolset_visibility_filter(user_id),
        )
        result = await session.exec(stmt)
        for toolset in result.all():
            if toolset.id is not None:
                toolsets_by_id[toolset.id] = toolset

    haystack_tools: list[Any] = []

    for toolset_id, tools_map in selected.items():
        toolset = toolsets_by_id.get(toolset_id)
        if toolset is None:
            raise HTTPException(
                status_code=500,
                detail=f"Toolset {toolset_id} not loaded for agent {agent.id}",
            )
        if not can_read_toolset(toolset, user_id):
            raise HTTPException(
                status_code=403,
                detail=f"Toolset {toolset.id} is not accessible to you",
            )

        db_tools = list(tools_map.values())
        token = await get_user_toolset_token(session, user_id, toolset)

        if toolset.type == ToolType.MCP:
            if toolset.auth_required and token is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"MCP toolset {toolset.id} requires a per-user credential; "
                        f"configure it via PUT /tool/toolset/{toolset.id}/credential"
                    ),
                )
            tool_names = [t.name for t in db_tools]
            auth_required = toolset.auth_required
            auth_type = toolset.auth_type
            header = toolset.header
            try:
                if await asyncio.to_thread(is_valid_server, toolset.url, auth_required, auth_type, token, header):
                    haystack_tools.append(
                        await asyncio.to_thread(
                            MCP,
                            toolset.url,
                            tool_names or None,
                            auth_required,
                            auth_type,
                            token,
                            header,
                        )
                    )
                else:
                    logger.error("Invalid MCP server: %s", toolset.url)
                    raise HTTPException(
                        status_code=502,
                        detail=f"MCP toolset {toolset.id} is unavailable",
                    )
            except Exception as e:
                logger.error("Error adding MCP toolset %s: %s", toolset.url, e)
                if isinstance(e, HTTPException):
                    raise
                raise HTTPException(
                    status_code=502,
                    detail=f"MCP toolset {toolset.id} is unavailable",
                ) from e

        elif toolset.type == ToolType.HTTP:
            if toolset.auth_required and token is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"HTTP toolset {toolset.id} requires a per-user credential; "
                        f"configure it via PUT /tool/toolset/{toolset.id}/credential"
                    ),
                )
            haystack_tools.append(
                http_toolset_factory(toolset, db_tools, token=token, user_id=user_id)
            )

    return haystack_tools
