import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastembed import TextEmbedding
from haystack.tools import Toolset, tool
from sqlmodel import select, literal

from src.db.db import async_session
from src.db.models import Memory

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

_model: TextEmbedding | None = None


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=EMBEDDING_MODEL)
    return _model


def _embed(text: str) -> list[float]:
    return list(_get_model().embed([text]))[0].tolist()


def _run_in_fresh_loop(coroutine):
    return asyncio.run(coroutine)


def _run_async(coroutine):
    """
    Execute async DB code from sync Haystack tools.
    If an event loop is already running, run the coroutine in a worker thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_in_fresh_loop, coroutine)
        return future.result()


async def _store_memory(content: str, category: str | None = None) -> dict:
    async with async_session() as session:
        memory = Memory(
            content=content,
            category=category,
            embedding=_embed(content),
        )
        session.add(memory)
        await session.commit()
        await session.refresh(memory)
        return {"id": memory.id}


async def _recall_memory(query: str, limit: int = 10, category: str | None = None) -> list[dict]:
    async with async_session() as session:
        distance = Memory.embedding.cosine_distance(_embed(query))
        similarity = (literal(1.0) - distance).label("similarity")
        statement = (
            select(Memory, similarity)
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


async def _list_memories(limit: int = 10, category: str | None = None) -> list[dict]:
    async with async_session() as session:
        statement = (
            select(Memory)
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


async def _delete_memory(memory_id: int) -> dict:
    async with async_session() as session:
        memory = await session.get(Memory, memory_id)
        if memory is None:
            return {"deleted": False}
        await session.delete(memory)
        await session.commit()
        return {"deleted": True}


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
    return _run_async(_store_memory(content, category))


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
    return _run_async(_recall_memory(query, limit, category))


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
    return _run_async(_list_memories(limit, category))


@tool(name="memory_delete")
def memory_delete(memory_id: int) -> dict:
    """
    Delete a memory by id for the authenticated user.

    Args:
        memory_id: Memory id to delete.

    Returns:
        A dictionary with the deleted status.
    """
    return _run_async(_delete_memory(memory_id))


def MemoryToolset() -> Toolset:
    return Toolset([memory_store, memory_recall, memory_list_memories, memory_delete])
