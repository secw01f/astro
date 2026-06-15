import logging
import os
import asyncio
import redis.asyncio as redis

from fastapi import APIRouter, HTTPException, Request, Depends, Body
from typing import Annotated
from pwdlib import PasswordHash
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from settings import settings
from src.db.db import session_dep
from src.db.models import (
    Agent,
    AgentStackLink,
    AgentToolLink,
    AgentToolSetLink,
    Credential,
    LLM,
    Memory,
    Message,
    Stack,
    ToolSet,
    User,
    UserPublic,
    UserToolSetCredential,
)
from lib.auth.auth import (
    verify_token,
    create_user as create_user_record,
    create_token,
    generate_password,
    required_roles,
    get_password_reset_token_user_id,
    reset_password,
    delete_password_reset_token,
    check_password_reset_rate_limit,
    validate_password_strength,
)
from lib.auth.enums import Role
from lib.auth.models import Login, CreateUser, CreateUserResponse, ResetPassword, UpdateUser, UpdateMe
from lib.tool.service import delete_toolset_record

auth_router = APIRouter(prefix="/auth")
logger = logging.getLogger(__name__)

@auth_router.post("/token")
async def login(login: Login, session: session_dep) -> dict[str, str]:
    hash = PasswordHash.recommended()

    if login.username == "stack":
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            default_stack_user_active = await client.get(f"auth:default_stack_user_active")
        finally:
            await client.aclose()
        if default_stack_user_active != "1":
            raise HTTPException(status_code=403, detail="User not valid.")

    statement = select(User).where(User.username == login.username, User.enabled == True)
    result = await session.exec(statement)
    user = result.first()

    password_valid = False
    if user:
        password_valid = await asyncio.to_thread(hash.verify, login.password, user.password)
    if not user or not password_valid:
        logger.error(f"Failed auth attempt for {login.username}")
        raise HTTPException(status_code=401, detail="Invalid Username or Password")

    if user.username == "stack":
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            default_stack_user_active = await client.get(f"auth:default_stack_user_active")
            if default_stack_user_active != "1":
                raise HTTPException(status_code=403, detail="User not valid.")
            await client.delete(f"auth:default_stack_user_active")
            logger.info(f"Default stack user deleted from Redis")
        finally:
            await client.aclose()
        token = create_token(user.id, user.role, user.token_version, expires_in=10)
        stack_user_file = "/api/stack_user.json"
        try:
            os.remove(stack_user_file)
        except FileNotFoundError:
            pass
        return {"token": token, "expires": "10 minutes"}

    logger.info(f"User {user.username} logged in")

    return {"token": create_token(user.id, user.role, user.token_version)}


@auth_router.post("/user/reset-password")
async def password_reset(password: ResetPassword, session: session_dep) -> dict[str, str]:
    await check_password_reset_rate_limit(password.token)
    user_id = await get_password_reset_token_user_id(password.token)
    if user_id is None:
        raise HTTPException(status_code=403, detail="Invalid or expired password reset token")

    await reset_password(session, user_id, password.new_password)
    await delete_password_reset_token(password.token)

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

    sensitive_update = any(
        value is not None for value in (body.username, body.email, body.new_password)
    )
    if sensitive_update:
        if not body.current_password:
            raise HTTPException(status_code=400, detail="current_password is required")
        hash = PasswordHash.recommended()
        password_valid = await asyncio.to_thread(
            hash.verify,
            body.current_password,
            user.password,
        )
        if not password_valid:
            raise HTTPException(status_code=403, detail="Current password is invalid")

    if body.username is not None:
        user.username = body.username
    if body.email is not None:
        user.email = body.email
    if body.new_password is not None:
        validate_password_strength(body.new_password)
        hash = PasswordHash.recommended()
        user.password = await asyncio.to_thread(hash.hash, body.new_password)
    if sensitive_update:
        user.token_version += 1

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

    generated_password = user.password is None
    initial_password = user.password if user.password else generate_password(16)
    new_user = await create_user_record(session, user.username, user.email, initial_password, user.role)

    logger.info(f"User {new_user.id} created by {user_id}")

    return CreateUserResponse(
        user=UserPublic.model_validate(new_user),
        temporary_password=initial_password if generated_password else None,
    )

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
    security_sensitive = False
    if user_update.role is not None and user_update.role != user.role:
        user.role = user_update.role
        security_sensitive = True
    if user_update.enabled is not None and user_update.enabled != user.enabled:
        user.enabled = user_update.enabled
        security_sensitive = True
    if security_sensitive:
        user.token_version += 1

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

    credential_ids: set[int] = set()

    private_toolsets = (
        await session.exec(select(ToolSet).where(ToolSet.user_id == id))
    ).all()
    for toolset in private_toolsets:
        await delete_toolset_record(session, toolset, commit=False)
    await session.flush()

    toolset_credentials = (
        await session.exec(
            select(UserToolSetCredential).where(UserToolSetCredential.user_id == id)
        )
    ).all()
    credential_ids.update(row.credential_id for row in toolset_credentials)
    for row in toolset_credentials:
        await session.delete(row)
    await session.flush()

    stacks = (await session.exec(select(Stack).where(Stack.user_id == id))).all()
    for stack in stacks:
        if stack.id is None:
            continue
        messages = (
            await session.exec(select(Message).where(Message.stack_id == stack.id))
        ).all()
        for message in messages:
            await session.delete(message)
        stack_links = (
            await session.exec(
                select(AgentStackLink).where(AgentStackLink.stack_id == stack.id)
            )
        ).all()
        for link in stack_links:
            await session.delete(link)
        await session.delete(stack)

    agents = (await session.exec(select(Agent).where(Agent.user_id == id))).all()
    for agent in agents:
        if agent.id is None:
            continue
        for model, field in (
            (AgentStackLink, AgentStackLink.agent_id),
            (AgentToolSetLink, AgentToolSetLink.agent_id),
            (AgentToolLink, AgentToolLink.agent_id),
        ):
            links = (await session.exec(select(model).where(field == agent.id))).all()
            for link in links:
                await session.delete(link)
        await session.delete(agent)

    llms = (await session.exec(select(LLM).where(LLM.user_id == id))).all()
    for llm in llms:
        if llm.credential_id is not None:
            credential_ids.add(llm.credential_id)
        await session.delete(llm)

    memories = (await session.exec(select(Memory).where(Memory.user_id == id))).all()
    for memory in memories:
        await session.delete(memory)

    owned_credentials = (
        await session.exec(select(Credential).where(Credential.user_id == id))
    ).all()
    credential_ids.update(
        credential.id for credential in owned_credentials if credential.id is not None
    )
    for credential_id in credential_ids:
        credential = await session.get(Credential, credential_id)
        if credential is not None:
            await session.delete(credential)

    deleted_user_id = user.id
    await session.delete(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="User has dependent records") from exc

    logger.info(f"User {deleted_user_id} deleted by {user_id}")

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
