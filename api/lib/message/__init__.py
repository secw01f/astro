import asyncio
import json

from sqlmodel import select
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
    position_state: dict[str, int],
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
        elif item["type"] == "end":
            full_message = messages.get(key, "")

            pos = position_state["next"]
            position_state["next"] = pos + 1

            session.add(
                Message(
                    role="assistant",
                    content=full_message,
                    stack_id=stack_id,
                    position=pos,
                )
            )

            await session.commit()
            messages.pop(key, None)

async def fanout(
    source: asyncio.Queue,
    client_queue: asyncio.Queue,
    storage_queue: asyncio.Queue,
    *,
    storage_only_types: frozenset[str] = frozenset({"response"}),
):
    while True:
        item = await source.get()

        if item is None:
            await client_queue.put(item)
            await storage_queue.put(item)
            break

        typ = item.get("type") if isinstance(item, dict) else None
        if typ not in storage_only_types:
            await client_queue.put(item)
        await storage_queue.put(item)

async def next_position(session, stack_id: int, user_id: str) -> int:
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