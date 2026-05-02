import logging
import os
import redis.asyncio as redis

from fastapi import APIRouter, HTTPException, Request, Depends, Body
from typing import Annotated
from pwdlib import PasswordHash
from sqlmodel import select

from settings import settings
from src.db.db import session_dep
from src.db.models import User, UserPublic
from lib.auth.auth import (
    verify_token,
    create_user as create_user_record,
    create_token,
    generate_password,
    required_roles,
    set_password_reset_required,
    password_reset_required,
    create_password_reset_token,
    get_password_reset_token_user_id,
    reset_password,
    delete_password_reset_token,
)
from lib.auth.enums import Role
from lib.auth.models import Login, CreateUser, CreateUserResponse, ResetPassword, UpdateUser, UpdateMe

auth_router = APIRouter(prefix="/auth")
logger = logging.getLogger(__name__)

@auth_router.post("/token")
async def login(login: Login, session: session_dep) -> dict[str, str]:
    hash = PasswordHash.recommended()

    if login.username == "stack":
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        default_stack_user_active = await client.get(f"auth:default_stack_user_active")
        if default_stack_user_active != "1":
            statement = select(User).where(User.username == "stack", User)
            result = await session.exec(statement)
            user = result.first()
            user.enabled = False
            raise HTTPException(status_code=403, detail="User not valid.")

    statement = select(User).where(User.username == login.username, User.enabled == True)
    result = await session.exec(statement)
    user = result.first()

    if not user or not hash.verify(login.password, user.password):
        logger.error(f"Failed auth attempt for {login.username}")
        raise HTTPException(status_code=401, detail="Invalid Username or Password")

    if await password_reset_required(user.id):
        raise HTTPException(status_code=403, detail="Password reset required")

    if user.username == "stack":
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        default_stack_user_active = await client.get(f"auth:default_stack_user_active")
        if default_stack_user_active != "1":
            raise HTTPException(status_code=403, detail="User not valid.")
        await client.delete(f"auth:default_stack_user_active")
        logger.info(f"Default stack user deleted from Redis")
        await client.aclose()
        token = create_token(user.id, user.role, expires_in=10)
        stack_user_file = "/api/stack_user.json"
        try:
            os.remove(stack_user_file)
        except FileNotFoundError:
            pass
        return {"token": token, "expires": "10 minutes"}

    logger.info(f"User {user.username} logged in")

    return {"token": create_token(user.id, user.role)}


@auth_router.post("/user/reset-password")
async def password_reset(token: str, password: ResetPassword, session: session_dep) -> dict[str, str]:
    user_id = await get_password_reset_token_user_id(token)
    if user_id is None:
        raise HTTPException(status_code=403, detail="Invalid or expired password reset token")

    await reset_password(session, user_id, password.new_password)
    await delete_password_reset_token(token)

    logger.info(f"User {user_id} reset password")

    return {"message": "Password reset successful"}

@auth_router.get("/user/me")
async def get_user(request: Request, session: session_dep, _auth: Annotated[None, Depends(verify_token)]) -> dict[str, UserPublic]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]
    statement = select(User).where(User.id == user_id)
    result = await session.exec(statement)
    user = result.first()
    return {"user": UserPublic.model_validate(user)}

@auth_router.patch("/user/me")
async def update_user_me(request: Request, body: Annotated[UpdateMe, Body(...)], session: session_dep, _auth: Annotated[None, Depends(verify_token)]) -> dict[str, UserPublic]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]
    statement = select(User).where(User.id == user_id)
    result = await session.exec(statement)
    user = result.first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.username is not None:
        user.username = body.username
    if body.email is not None:
        user.email = body.email
    if body.new_password is not None:
        hash = PasswordHash.recommended()
        user.password = hash.hash(body.new_password)

    await session.commit()
    await session.refresh(user)

    logger.info(f"User {user.id} updated by {user_id}")

    return {"user": UserPublic.model_validate(user)}

@auth_router.post("/user/create", response_model=CreateUserResponse)
async def create_user(request: Request, user: CreateUser, session: session_dep, _roles: Annotated[None, Depends(required_roles([Role.ADMIN]))]) -> CreateUserResponse:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    initial_password = user.password if user.password else generate_password(16)
    new_user = await create_user_record(session, user.username, user.email, initial_password, user.role)

    await set_password_reset_required(new_user.id)
    reset_token = await create_password_reset_token(new_user.id)

    logger.info(f"User {new_user.id} created by {user_id}")
    logger.info(f"Password reset required for {new_user.id}")

    return CreateUserResponse(user=UserPublic.model_validate(new_user), reset_token=reset_token)

@auth_router.patch("/user/{id}")
async def update_user(request: Request, id: int, user_update: UpdateUser, session: session_dep, _roles: Annotated[None, Depends(required_roles([Role.ADMIN]))]) -> dict[str, UserPublic]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    statement = select(User).where(User.id == id)
    result = await session.exec(statement)
    user = result.first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user_update.username is not None:
        user.username = user_update.username
    if user_update.email is not None:
        user.email = user_update.email
    if user_update.role is not None:
        user.role = user_update.role
    if user_update.enabled is not None:
        user.enabled = user_update.enabled

    await session.commit()
    await session.refresh(user)

    logger.info(f"User {user.id} updated by {claims['id']}")

    return {"user": UserPublic.model_validate(user)}

@auth_router.delete("/user/{id}")
async def delete_user(request: Request, id: int, session: session_dep, _roles: Annotated[None, Depends(required_roles([Role.ADMIN]))]) -> dict[str, str]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    if user_id == id:
        raise HTTPException(status_code=403, detail="You cannot delete yourself")

    statement = select(User).where(User.id == id)
    result = await session.exec(statement)
    user = result.first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await session.delete(user)
    await session.commit()

    logger.info(f"User {user.id} deleted by {user_id}")

    return {"message": "User deleted successfully"}

@auth_router.get("/user/{id}")
async def get_user_by_id(request: Request, id: int, session: session_dep, _roles: Annotated[None, Depends(required_roles([Role.ADMIN]))]) -> dict[str, UserPublic]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    statement = select(User).where(User.id == id)
    result = await session.exec(statement)
    user = result.first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": UserPublic.model_validate(user)}

@auth_router.get("/users")
async def get_all_users(request: Request, session: session_dep, _roles: Annotated[None, Depends(required_roles([Role.ADMIN]))]) -> dict[str, list[UserPublic]]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    statement = select(User)
    result = await session.exec(statement)
    users = result.all()
    return {"users": [UserPublic.model_validate(user) for user in users]}