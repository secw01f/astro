import asyncio

from fastembed import TextEmbedding
from haystack.tools import Toolset, tool
from sqlmodel import select, literal

from src.db.db import async_session
from src.db.models import Memory
from lib.tool import run_sync

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

_model: TextEmbedding | None = None

def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=EMBEDDING_MODEL)
    return _model

def _embed(text: str) -> list[float]:
    return list(_get_model().embed([text]))[0].tolist()

async def _store_memory(user_id: int, content: str, category: str | None = None) -> dict:
    async with async_session() as session:
        memory = Memory(
            content=content,
            category=category,
            embedding=_embed(content),
            user_id=user_id,
        )
        session.add(memory)
        await session.commit()
        await session.refresh(memory)
        return {"id": memory.id}

async def _recall_memory(
    user_id: int, query: str, limit: int = 10, category: str | None = None
) -> list[dict]:
    async with async_session() as session:
        distance = Memory.embedding.cosine_distance(_embed(query))
        similarity = (literal(1.0) - distance).label("similarity")
        statement = (
            select(Memory, similarity)
            .where(Memory.user_id == user_id)
            .order_by(distance)
            .limit(limit)
        )
        if category is not None:
            statement = statement.where(Memory.category == category)

        result = await session.exec(statement)
        memories = result.all()
        return [
            {
                "id": mem.id,
                "content": mem.content,
                "category": mem.category,
                "similarity": round(float(sim), 4),
                "created": mem.created.isoformat(),
            }
            for mem, sim in memories
        ]

async def _list_memories(user_id: int, limit: int = 10, category: str | None = None) -> list[dict]:
    async with async_session() as session:
        statement = (
            select(Memory)
            .where(Memory.user_id == user_id)
            .order_by(Memory.created.desc())
            .limit(limit)
        )
        if category is not None:
            statement = statement.where(Memory.category == category)
        result = await session.exec(statement)
        memories = result.all()
        return [
            {
                "id": mem.id,
                "content": mem.content,
                "category": mem.category,
                "created": mem.created.isoformat(),
            }
            for mem in memories
        ]

async def _delete_memory(user_id: int, memory_id: int) -> dict:
    async with async_session() as session:
        memory = await session.get(Memory, memory_id)
        if memory is None or memory.user_id != user_id:
            return {"deleted": False}
        await session.delete(memory)
        await session.commit()
        return {"deleted": True}

def MemoryToolset(user_id: int, *, app_loop: asyncio.AbstractEventLoop | None = None) -> Toolset:
    @tool(name="memory_store")
    def memory_store(content: str, category: str | None = None) -> dict:
        """
        Store information in long-term memory.

        Args:
            content: The memory text to store.
            category: Optional category label for filtering.

        Returns:
            The memory id
        """
        return run_sync(_store_memory(user_id, content, category), app_loop=app_loop)

    @tool(name="memory_recall")
    def memory_recall(query: str, limit: int = 10, category: str | None = None) -> list[dict]:
        """
        Recall memories for the authenticated user.

        Args:
            query: Natural language query to match memories.
            category: Optional category filter.
            limit: Maximum number of results (default 10).

        Returns:
            A list of memories.
        """
        return run_sync(_recall_memory(user_id, query, limit, category), app_loop=app_loop)

    @tool(name="memory_list")
    def memory_list_memories(limit: int = 15, category: str | None = None) -> list[dict]:
        """
        List memories for the authenticated user.

        Args:
            category: Optional category filter.
            limit: Maximum memories to return (default 15).

        Returns:
            A list of memories.
        """
        return run_sync(_list_memories(user_id, limit, category), app_loop=app_loop)

    @tool(name="memory_delete")
    def memory_delete(memory_id: int) -> dict:
        """
        Delete a memory by id for the authenticated user.

        Args:
            memory_id: Memory id to delete.

        Returns:
            A dictionary with the deleted status.
        """
        return run_sync(_delete_memory(user_id, memory_id), app_loop=app_loop)

    return Toolset([memory_store, memory_recall, memory_list_memories, memory_delete])
