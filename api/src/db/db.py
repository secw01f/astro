import asyncio
import logging

from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text
from typing import Annotated
from fastapi import Depends

from settings import settings
from src.db import models

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.DB_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    max_retries = 10
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            async with engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await conn.run_sync(SQLModel.metadata.create_all)

        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
            else:
                raise e

async def get_db():
    async with async_session() as session:
        yield session

session_dep = Annotated[AsyncSession, Depends(get_db)]