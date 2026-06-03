import asyncio
import httpx

from pydantic import BaseModel
from lib.tool import create_tool_registry

from duckduckgo_api_haystack import DuckduckgoApiWebSearch

Registry, tool = create_tool_registry("web")

REQUEST_TIMEOUT_SECONDS = 30.0

BLACKLISTED_DOMAINS = ["localhost", "127.0.0.1", "169.254.169.254"]

def _error_response(error: str, url: str) -> dict:
    return {"error": error, "url": url}

def _format_response(response: httpx.Response) -> dict:
    try:
        return response.json()
    except ValueError:
        return {
            "status_code": response.status_code,
            "content": response.text,
        }

class GetInput(BaseModel):
    url: str

class PostInput(BaseModel):
    url: str
    json: dict | None = None
    form: dict[str, str | int | float | bool] | None = None

class PutInput(BaseModel):
    url: str
    json: dict | None = None
    form: dict[str, str | int | float | bool] | None = None

class PatchInput(BaseModel):
    url: str
    json: dict | None = None
    form: dict[str, str | int | float | bool] | None = None

class DeleteInput(BaseModel):
    url: str

@tool(name="get", description="Get from a URL", capabilities=["get"], version="1.0")
async def get(input: GetInput) -> dict:
    if any(domain in input.url for domain in BLACKLISTED_DOMAINS):
        return _error_response("Execution Blocked", input.url)

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(input.url)
        return _format_response(response)
    except httpx.TimeoutException:
        return _error_response("Request timed out", input.url)
    except httpx.RequestError as e:
        return _error_response(f"Request failed: {e}", input.url)

@tool(name="post", description="Post to a URL", capabilities=["post"], version="1.0")
async def post(input: PostInput) -> dict:
    if any(domain in input.url for domain in BLACKLISTED_DOMAINS):
        return _error_response("Execution Blocked", input.url)

    if input.json is not None and input.form is not None:
        return {
            "error": "Provide either json or form (multipart), not both."
        }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            if input.form is not None:
                form_data = {key: str(value) for key, value in input.form.items()}
                response = await client.post(input.url, files=form_data)
            else:
                response = await client.post(input.url, json=input.json or {})
        return _format_response(response)
    except httpx.TimeoutException:
        return _error_response("Request timed out", input.url)
    except httpx.RequestError as e:
        return _error_response(f"Request failed: {e}", input.url)

@tool(name="put", description="Put to a URL", capabilities=["put"], version="1.0")
async def put(input: PutInput) -> dict:
    if any(domain in input.url for domain in BLACKLISTED_DOMAINS):
        return _error_response("Execution Blocked", input.url)

    if input.json is not None and input.form is not None:
        return {
            "error": "Provide either json or form (multipart), not both."
        }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            if input.form is not None:
                form_data = {key: str(value) for key, value in input.form.items()}
                response = await client.put(input.url, files=form_data)
            else:
                response = await client.put(input.url, json=input.json or {})
        return _format_response(response)
    except httpx.TimeoutException:
        return _error_response("Request timed out", input.url)
    except httpx.RequestError as e:
        return _error_response(f"Request failed: {e}", input.url)

@tool(name="patch", description="Patch to a URL", capabilities=["patch"], version="1.0")
async def patch(input: PatchInput) -> dict:
    if any(domain in input.url for domain in BLACKLISTED_DOMAINS):
        return _error_response("Execution Blocked", input.url)

    if input.json is not None and input.form is not None:
        return {
            "error": "Provide either json or form (multipart), not both."
        }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            if input.form is not None:
                form_data = {key: str(value) for key, value in input.form.items()}
                response = await client.patch(input.url, files=form_data)
            else:
                response = await client.patch(input.url, json=input.json or {})
        return _format_response(response)
    except httpx.TimeoutException:
        return _error_response("Request timed out", input.url)
    except httpx.RequestError as e:
        return _error_response(f"Request failed: {e}", input.url)

@tool(name="delete", description="Delete from a URL", capabilities=["delete"], version="1.0")
async def delete(input: DeleteInput) -> dict:
    if any(domain in input.url for domain in BLACKLISTED_DOMAINS):
        return _error_response("Execution Blocked", input.url)

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.delete(input.url)
        return _format_response(response)
    except httpx.TimeoutException:
        return _error_response("Request timed out", input.url)
    except httpx.RequestError as e:
        return _error_response(f"Request failed: {e}", input.url)

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
