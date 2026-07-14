import asyncio
import json

from sqlmodel import select, func
from fastapi import HTTPException

from src.db.models import Message, Stack

async def event_stream(queue: asyncio.Queue):
    while True:
        item = await queue.get()

        if item is None:
            break

        yield f"data: {json.dumps(item)}\n\n"

async def storage_consumer(
    queue: asyncio.Queue,
    session,
    stack_id: int,
):
    messages = {}

    async def _persist_message(role: str, content: str) -> None:
        position = await reserve_position(session, stack_id)
        session.add(
            Message(
                role=role,
                content=content,
                stack_id=stack_id,
                position=position,
            )
        )
        await session.commit()

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
            await _persist_message("tool", json.dumps(payload, default=str))
        elif item["type"] == "end":
            full_message = messages.get(key, "")
            await _persist_message("assistant", full_message)
            messages.pop(key, None)

async def fanout(
    source: asyncio.Queue,
    client_queue: asyncio.Queue,
    storage_queue: asyncio.Queue,
    *,
    storage_only_types: frozenset[str] = frozenset({"response"}),
    verbose: bool = True,
    supervisor_agent_name: str | None = None,
):
    while True:
        item = await source.get()

        if item is None:
            await client_queue.put(item)
            await storage_queue.put(item)
            break

        typ = item.get("type") if isinstance(item, dict) else None
        to_client = typ not in storage_only_types
        if typ == "file_request":
            to_client = True
        if typ == "tool_call":
            to_client = False
        elif typ == "tool_result":
            # Surface tool results only in verbose mode; the client uses a
            # supporting agent's own tool_result (tool_name == agent name) as a
            # deterministic signal that its buffered reply is complete.
            to_client = verbose
        if to_client and not verbose and supervisor_agent_name is not None:
            agent_name = item.get("agent") if isinstance(item, dict) else None
            if agent_name != supervisor_agent_name:
                to_client = False
        if to_client:
            await client_queue.put(item)
        await storage_queue.put(item)

async def reserve_position(session, stack_id: int) -> int:
    """Atomically reserve the next message position for a stack.

    Locks the stack row (``FOR UPDATE``) so concurrent runs on the same stack
    are serialized, and reconciles ``last_position`` against the current
    ``MAX(position)`` so the returned value is always beyond every existing
    message. The caller is responsible for committing.
    """
    stmt = select(Stack).where(Stack.id == stack_id).with_for_update()
    stack = (await session.exec(stmt)).first()

    if not stack:
        raise HTTPException(status_code=404, detail="Stack not found")

    max_stmt = select(func.max(Message.position)).where(Message.stack_id == stack_id)
    max_position = (await session.exec(max_stmt)).one()
    if max_position is not None and max_position > stack.last_position:
        stack.last_position = max_position

    stack.last_position += 1
    session.add(stack)

    return stack.last_position


async def next_position(session, stack_id: int, user_id: str) -> int:
    """Reserve a position after verifying the stack belongs to ``user_id``."""
    owner_stmt = select(Stack.id).where(Stack.id == stack_id, Stack.user_id == user_id)
    if (await session.exec(owner_stmt)).first() is None:
        raise HTTPException(status_code=404, detail="Stack not found")

    return await reserve_position(session, stack_id)