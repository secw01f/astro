import asyncio
import logging

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from typing import Annotated
from fastapi import Depends

from settings import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.DB_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with async_session() as session:
        yield session

session_dep = Annotated[AsyncSession, Depends(get_db)]


def run_celery_async(coro):
    """Run async code in Celery with a fresh event loop and clean connection pool."""

    async def _runner():
        try:
            return await coro
        finally:
            await engine.dispose()

    return asyncio.run(_runner())