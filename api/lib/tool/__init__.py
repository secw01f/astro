from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from haystack.tools import Tool, Toolset, ComponentTool, SearchableToolset
from haystack_integrations.tools.mcp import MCPToolset
from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from src.db.models import ToolSet

from lib.tool.access import user_has_toolset_credential

def toolset(tools: list[Tool | Toolset | ComponentTool | MCPToolset]) -> SearchableToolset:
    catalog = tools
    return SearchableToolset(catalog=catalog)

def run_sync(coro, *, app_loop: asyncio.AbstractEventLoop | None = None):
    if app_loop is not None:
        fut = asyncio.run_coroutine_threadsafe(coro, app_loop)
        return fut.result()

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()

async def validate_toolsets_ready_for_agent(
    session: AsyncSession,
    user_id: int,
    toolsets: list[ToolSet],
) -> None:
    unconfigured_auth_toolsets: list[int] = []
    for toolset in toolsets:
        if toolset.id is None or not toolset.auth_required:
            continue
        if not await user_has_toolset_credential(session, user_id, toolset):
            unconfigured_auth_toolsets.append(toolset.id)
    if unconfigured_auth_toolsets:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "One or more toolsets require auth but have no credential configured for your user",
                "toolset_ids": sorted(unconfigured_auth_toolsets),
            },
        )