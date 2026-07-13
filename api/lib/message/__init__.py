import asyncio
import json

from sqlmodel import select
from fastapi import HTTPException

from src.db.models import Message, Stack

async def event_stream(queue: asyncio.Queue, closed: asyncio.Event | None = None):
    try:
        while True:
            item = await queue.get()

            if item is None:
                break

            yield f"data: {json.dumps(item)}\n\n"
    finally:
        if closed is not None:
            closed.set()


async def _persist_message(session, stack_id: int, user_id: int, role: str, content: str) -> None:
    pos = await next_position(session, stack_id, user_id)
    session.add(
        Message(
            role=role,
            content=content,
            stack_id=stack_id,
            position=pos,
        )
    )
    await session.commit()

async def storage_consumer(
    queue: asyncio.Queue,
    session,
    stack_id: int,
    user_id: int,
):
    messages = {}

    while True:
        item = await queue.get()

        if item is None:
            break

        key = (item["agent"], item["run_id"])

        if item["type"] == "start":
            messages[key] = ""
        elif item["type"] == "token":
            messages[key] = messages.get(key, "") + item["content"]
        elif item["type"] == "response":
            messages[key] = item.get("content") or ""
        elif item["type"] == "tool_result":
            payload = {
                "kind": "tool_result",
                "agent": item.get("agent"),
                "run_id": item.get("run_id"),
                "tool_name": item.get("tool_name"),
                "tool_call_id": item.get("tool_call_id"),
                "arguments_preview": item.get("arguments_preview"),
                "result_preview": item.get("result_preview"),
                "error": item.get("error"),
                "finish_reason": item.get("finish_reason"),
                "timestamp": item.get("timestamp"),
            }
            await _persist_message(session, stack_id, user_id, "tool", json.dumps(payload, default=str))
        elif item["type"] == "end":
            full_message = messages.get(key, "")
            await _persist_message(session, stack_id, user_id, "assistant", full_message)
            messages.pop(key, None)

    for full_message in messages.values():
        if full_message:
            await _persist_message(session, stack_id, user_id, "assistant", full_message)


def _try_put_nowait(queue: asyncio.Queue, item) -> None:
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        pass

async def fanout(
    source: asyncio.Queue,
    client_queue: asyncio.Queue,
    storage_queue: asyncio.Queue,
    *,
    storage_only_types: frozenset[str] = frozenset({"response"}),
    verbose: bool = True,
    supervisor_agent_name: str | None = None,
    client_closed: asyncio.Event | None = None,
):
    while True:
        item = await source.get()

        if item is None:
            if client_closed is None or not client_closed.is_set():
                _try_put_nowait(client_queue, item)
            await storage_queue.put(item)
            break

        typ = item.get("type") if isinstance(item, dict) else None
        to_client = typ not in storage_only_types
        if typ == "file_request":
            to_client = True
        if typ in ("tool_call", "tool_result"):
            to_client = False
        if to_client and not verbose and supervisor_agent_name is not None:
            agent_name = item.get("agent") if isinstance(item, dict) else None
            if agent_name != supervisor_agent_name:
                to_client = False
        if to_client and (client_closed is None or not client_closed.is_set()):
            _try_put_nowait(client_queue, item)
        await storage_queue.put(item)

async def next_position(session, stack_id: int, user_id: int) -> int:
    stmt = (
        select(Stack)
        .where(Stack.id == stack_id, Stack.user_id == user_id)
        .with_for_update()
    )

    result = await session.exec(stmt)
    stack = result.first()

    if not stack:
        raise HTTPException(status_code=404, detail="Stack not found")

    stack.last_position += 1
    session.add(stack)

    return stack.last_position
