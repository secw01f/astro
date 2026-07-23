import asyncio

from fastembed import TextEmbedding
from haystack.tools import Toolset, tool
from sqlmodel import select, literal

from settings import settings
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


def _truncate_text(content: str, max_chars: int) -> tuple[str, bool]:
    if len(content) <= max_chars:
        return content, False
    return content[:max_chars].rstrip() + "... [truncated]", True


def _trim_memory_rows(rows: list[dict]) -> list[dict]:
    per_item_limit = max(1, settings.MEMORY_ITEM_MAX_CHARS)
    total_limit = max(1, settings.TOOL_OUTPUT_MAX_CHARS)

    trimmed: list[dict] = []
    total_chars = 0
    for row in rows:
        content = str(row.get("content", ""))
        truncated_content, content_was_truncated = _truncate_text(content, per_item_limit)
        candidate = {**row, "content": truncated_content}
        if content_was_truncated:
            candidate["truncated"] = True

        candidate_chars = len(str(candidate))
        if trimmed and total_chars + candidate_chars > total_limit:
            break
        trimmed.append(candidate)
        total_chars += candidate_chars
    return trimmed

async def _store_memory(user_id: int, stack_id: int, content: str, category: str | None = None) -> dict:
    embedding = await asyncio.to_thread(_embed, content)
    async with async_session() as session:
        memory = Memory(
            content=content,
            category=category,
            embedding=embedding,
            user_id=user_id,
            stack_id=stack_id,
        )
        session.add(memory)
        await session.commit()
        await session.refresh(memory)
        return {"id": memory.id}

async def _recall_memory(
    user_id: int, stack_id: int, query: str, limit: int = 2, category: str | None = None
) -> list[dict]:
    safe_limit = max(1, min(limit, settings.MEMORY_RECALL_MAX_ITEMS))
    query_embedding = await asyncio.to_thread(_embed, query)
    async with async_session() as session:
        distance = Memory.embedding.cosine_distance(query_embedding)
        similarity = (literal(1.0) - distance).label("similarity")
        statement = (
            select(Memory, similarity)
            .where(Memory.user_id == user_id, Memory.stack_id == stack_id)
            .order_by(distance)
            .limit(safe_limit)
        )
        if category is not None:
            statement = statement.where(Memory.category == category)

        result = await session.exec(statement)
        memories = result.all()
        rows = [
            {
                "id": mem.id,
                "content": mem.content,
                "category": mem.category,
                "similarity": round(float(sim), 4),
                "created": mem.created.isoformat(),
            }
            for mem, sim in memories
        ]
        return _trim_memory_rows(rows)

async def _list_memories(user_id: int, stack_id: int, limit: int = 10, category: str | None = None) -> list[dict]:
    safe_limit = max(1, min(limit, settings.MEMORY_LIST_MAX_ITEMS))
    async with async_session() as session:
        statement = (
            select(Memory)
            .where(Memory.user_id == user_id, Memory.stack_id == stack_id)
            .order_by(Memory.created.desc())
            .limit(safe_limit)
        )
        if category is not None:
            statement = statement.where(Memory.category == category)
        result = await session.exec(statement)
        memories = result.all()
        rows = [
            {
                "id": mem.id,
                "content": mem.content,
                "category": mem.category,
                "created": mem.created.isoformat(),
            }
            for mem in memories
        ]
        return _trim_memory_rows(rows)

async def _delete_memory(user_id: int, stack_id: int, memory_id: int) -> dict:
    async with async_session() as session:
        memory = await session.get(Memory, memory_id)
        if memory is None or memory.user_id != user_id or memory.stack_id != stack_id:
            return {"deleted": False}
        await session.delete(memory)
        await session.commit()
        return {"deleted": True}

def MemoryToolset(user_id: int, stack_id: int, *, app_loop: asyncio.AbstractEventLoop | None = None) -> Toolset:
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
        return run_sync(_store_memory(user_id, stack_id, content, category), app_loop=app_loop)

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
        return run_sync(_recall_memory(user_id, stack_id, query, limit, category), app_loop=app_loop)

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
        return run_sync(_list_memories(user_id, stack_id, limit, category), app_loop=app_loop)

    @tool(name="memory_delete")
    def memory_delete(memory_id: int) -> dict:
        """
        Delete a memory by id for the authenticated user.

        Args:
            memory_id: Memory id to delete.

        Returns:
            A dictionary with the deleted status.
        """
        return run_sync(_delete_memory(user_id, stack_id, memory_id), app_loop=app_loop)

    return Toolset([memory_store, memory_recall, memory_list_memories, memory_delete])
