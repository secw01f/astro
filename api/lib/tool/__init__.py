from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from haystack.tools import Tool, Toolset, ComponentTool, SearchableToolset
from haystack_integrations.tools.mcp import MCPToolset

def toolset(tools: list[Tool | Toolset | ComponentTool | MCPToolset]) -> SearchableToolset:
    catalog = tools
    return SearchableToolset(catalog=catalog)

def run_sync(coro, *, app_loop: asyncio.AbstractEventLoop | None = None):
    """
    Execute a coroutine that uses the shared async_engine / async_session.

    When tools run on a worker thread (e.g. Agent.run inside asyncio.to_thread), there is
    no compatible running loop; asyncio.run() would create a new loop and asyncpg raises
    "Future attached to a different loop". Pass the FastAPI event loop so the coroutine is
    scheduled with run_coroutine_threadsafe.

    When ``app_loop`` is omitted, falls back to prior behavior for simple call sites.
    """
    if app_loop is not None:
        fut = asyncio.run_coroutine_threadsafe(coro, app_loop)
        return fut.result()

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()