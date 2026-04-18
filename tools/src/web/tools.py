from pydantic import BaseModel
from lib.tool import create_tool_registry

from duckduckgo_api_haystack import DuckduckgoApiWebSearch

Registry, tool = create_tool_registry("web")

class SearchInput(BaseModel):
    query: str
    max_results: int = 10

@tool(name="search", description="Duck Duck Go Web Search Tool", capabilities=["websearch"], version="1.0")
async def search(input: SearchInput) -> list[dict]:
    websearch = DuckduckgoApiWebSearch(top_k=input.max_results)
    results = websearch.run(query=input.query)

    docs = results.get("documents", [])

    return [
        {
            "title": doc.meta.get("title", ""),
            "link": doc.meta.get("link", ""),
            "content": doc.content,
        }
        for doc in docs
    ]
