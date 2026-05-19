import asyncio
import base64
import uuid

from haystack.tools import Toolset, tool

from lib.file.request import FileRunSession
from lib.file.storage import get_user_file, list_user_files
from lib.tool import run_sync

_MAX_TOOL_TEXT_CHARS = 8000


def _truncate(text: str, limit: int = _MAX_TOOL_TEXT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "... [truncated]"


async def _list_files(user_id: int, limit: int = 20) -> list[dict]:
    safe_limit = max(1, min(limit, 50))
    return list_user_files(user_id)[:safe_limit]


async def _read_file(user_id: int, file_id: str) -> dict:
    item = get_user_file(user_id, file_id)
    if item is None:
        return {"found": False}
    row, content = item
    try:
        decoded = content.decode("utf-8")
        return {
            "found": True,
            "id": row.get("id"),
            "filename": row.get("filename"),
            "content_type": row.get("content_type"),
            "size": row.get("size"),
            "text": _truncate(decoded),
            "encoding": "utf-8",
        }
    except UnicodeDecodeError:
        encoded = base64.b64encode(content).decode("ascii")
        return {
            "found": True,
            "id": row.get("id"),
            "filename": row.get("filename"),
            "content_type": row.get("content_type"),
            "size": row.get("size"),
            "base64": _truncate(encoded),
            "encoding": "base64",
        }


async def _request_file(
    user_id: int,
    file_session: FileRunSession,
    description: str,
) -> dict:
    request_id = str(uuid.uuid4())
    file_session.create_pending(request_id)
    file_session.emit_file_request(request_id, description.strip() or "File required")
    try:
        provided = await file_session.wait_for_file(request_id)
    except asyncio.TimeoutError:
        return {
            "status": "timeout",
            "request_id": request_id,
            "message": "Timed out waiting for the user to provide a file.",
        }
    except asyncio.CancelledError:
        return {
            "status": "cancelled",
            "request_id": request_id,
            "message": "Stack run ended before a file was provided.",
        }

    file_id = provided.get("file_id")
    if not file_id:
        return {
            "status": "error",
            "request_id": request_id,
            "message": "No file id returned from upload.",
        }

    read_result = await _read_file(user_id, str(file_id))
    read_result["status"] = "provided"
    read_result["request_id"] = request_id
    return read_result


def FileToolset(
    user_id: int,
    *,
    file_session: FileRunSession | None = None,
    app_loop: asyncio.AbstractEventLoop | None = None,
) -> Toolset:
    @tool(name="file_list")
    def file_list(limit: int = 20) -> list[dict]:
        """
        List files uploaded by the current user.

        Args:
            limit: Maximum number of files to return.
        """
        return run_sync(_list_files(user_id, limit), app_loop=app_loop)

    @tool(name="file_read")
    def file_read(file_id: str) -> dict:
        """
        Read a specific file uploaded by the current user.

        Args:
            file_id: File id to read.
        """
        return run_sync(_read_file(user_id, file_id), app_loop=app_loop)

    tools = [file_list, file_read]

    if file_session is not None:

        @tool(name="file_request")
        def file_request(description: str) -> dict:
            """
            Ask the user to provide a file. Execution pauses until the user uploads
            one using the request_id sent in the stream.

            Args:
                description: What file is needed and why (shown to the user).
            """
            return run_sync(
                _request_file(user_id, file_session, description),
                app_loop=app_loop,
            )

        tools.append(file_request)

    return Toolset(tools)
