from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from haystack.tools import Tool, Toolset, ComponentTool, SearchableToolset
from haystack_integrations.tools.mcp import MCPToolset

from src.db.models import ToolSet
from fastapi import HTTPException

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

def validate_toolsets_ready_for_agent(toolsets: list[ToolSet]) -> None:
    unconfigured_auth_toolsets = sorted(
        toolset.id for toolset in toolsets
        if toolset.id is not None and toolset.auth_required and toolset.credential_id is None
    )
    if unconfigured_auth_toolsets:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "One or more toolsets require auth but have no credential configured",
                "toolset_ids": unconfigured_auth_toolsets,
            },
        )