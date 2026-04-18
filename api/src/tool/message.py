import asyncio

from haystack.tools import Toolset, tool
from sqlmodel import select

from src.db.db import async_session
from src.db.models import Message
from lib.tool import run_sync

async def _get_message_history(stack: int, limit: int = 10) -> list[dict]:
    async with async_session() as session:
        statement = select(Message).where(Message.stack_id == stack).order_by(Message.created.desc()).limit(limit)
        result = await session.exec(statement)
        messages = result.all()
        return [
            {
                "id": message.id,
                "position": message.position,
                "role": message.role,
                "content": message.content, 
                "created": message.created.isoformat(),
            }
            for message in messages
        ]   

def MessageToolset(stack: int, *, app_loop: asyncio.AbstractEventLoop | None = None) -> Toolset:
    @tool(name="get_message_history")
    def get_message_history(limit: int = 10) -> list[dict]:
        """
        Get the message history for a stack.

        Args:
            limit: Maximum messages to return (default 10).

        Returns:
            A list of messages.
        """
        return run_sync(_get_message_history(stack, limit), app_loop=app_loop)

    return Toolset(tools=[get_message_history])