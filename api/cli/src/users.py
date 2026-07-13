import typer
import secrets
import asyncio

from typing import Annotated

from lib.auth.auth import create_user, generate_password
from lib.auth.enums import Role
from src.db.db import engine
from sqlmodel.ext.asyncio.session import AsyncSession

app = typer.Typer()

@app.command()
def create(
    email: Annotated[str, typer.Option(default=...)],
    username: Annotated[str, typer.Option(default=None)] = None,
    role: Annotated[Role, typer.Option(default=Role.USER)] = Role.USER
):
    async def _create_user():
        password = generate_password(12)
        async with AsyncSession(engine) as session:
            newuser_username = username or email
            await create_user(session, newuser_username, email, password, role)
            await session.commit()
        
        print(f"The user {newuser_username} has been created with role {role}")
        print(f"Initial password: {password}")
    
    asyncio.run(_create_user())
