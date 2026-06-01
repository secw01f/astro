import asyncio

from pydantic import BaseModel
from lib.tool import create_tool_registry

from duckduckgo_api_haystack import DuckduckgoApiWebSearch

Registry, tool = create_tool_registry("web")

class SearchInput(BaseModel):
    query: str
    max_results: int = 10

def _format_search_results(results: dict, query: str) -> dict:
    docs = results.get("documents") or []
    links = results.get("links") or []
    formatted: list[dict] = []
    for index, doc in enumerate(docs):
        meta = getattr(doc, "meta", None) or {}
        link = meta.get("link") or meta.get("url") or ""
        if not link and index < len(links):
            link = links[index]
        formatted.append(
            {
                "title": meta.get("title", ""),
                "link": link,
                "content": getattr(doc, "content", "") or "",
            }
        )
    if formatted:
        return {"query": query, "results": formatted}

    return {
        "query": query,
        "results": [],
        "error": (
            "Search completed but returned no results. "
            "DuckDuckGo may be rate-limited or temporarily unavailable; retry shortly."
        ),
    }

@tool(name="search", description="Duck Duck Go Web Search Tool", capabilities=["websearch"], version="1.0")
async def search(input: SearchInput) -> dict:
    websearch = DuckduckgoApiWebSearch(top_k=input.max_results, timeout=20)
    try:
        results = await asyncio.to_thread(websearch.run, query=input.query)
    except Exception as exc:
        return {
            "query": input.query,
            "results": [],
            "error": f"Web search failed: {exc}",
        }

    if not isinstance(results, dict):
        return {
            "query": input.query,
            "results": [],
            "error": "Search provider returned an unexpected response.",
        }

    return _format_search_results(results, input.query)
