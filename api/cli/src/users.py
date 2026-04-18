import typer
import secrets
import asyncio

from typing import Annotated

from lib.auth.auth import create_user, generate_password
from src.db.db import engine
from sqlmodel.ext.asyncio.session import AsyncSession

app = typer.Typer()

@app.command()
def create(
    email: Annotated[str, typer.Option(default=...)],
    username: Annotated[str, typer.Option(default=None)] = None
):
    async def _create_user():
        password = generate_password(12)
        async with AsyncSession(engine) as session:
            newuser_username = username or email
            await create_user(session, newuser_username, email, password)
            await session.commit()
        
        print(f"The user {email} has been created")
    
    asyncio.run(_create_user())
