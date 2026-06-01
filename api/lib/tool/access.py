from __future__ import annotations

from fastapi import HTTPException, Request
from sqlmodel import select, or_
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import selectinload

from lib.auth.enums import Role
from lib.credentials import decrypt_token, encrypt_token
from src.db.models import ToolSet, Credential, UserToolSetCredential

def claims_from_request(request: Request) -> tuple[int, Role]:
    claims = getattr(request.state, "claims", None)
    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")
    role_value = claims.get("role", Role.USER.value)
    try:
        role = Role(role_value)
    except ValueError:
        role = Role.USER
    return int(claims["id"]), role

def is_shared_toolset(toolset: ToolSet) -> bool:
    return toolset.user_id is None

def can_read_toolset(toolset: ToolSet, user_id: int) -> bool:
    return is_shared_toolset(toolset) or toolset.user_id == user_id

def can_write_toolset(toolset: ToolSet, user_id: int, role: Role) -> bool:
    if is_shared_toolset(toolset):
        return role == Role.ADMIN
    return toolset.user_id == user_id

def toolset_visibility_filter(user_id: int):
    return or_(ToolSet.user_id.is_(None), ToolSet.user_id == user_id)

async def get_toolset_or_404(
    session: AsyncSession,
    toolset_id: int,
    user_id: int,
    *,
    load_tools: bool = False,
) -> ToolSet:
    statement = select(ToolSet).where(ToolSet.id == toolset_id, toolset_visibility_filter(user_id))
    if load_tools:
        statement = statement.options(selectinload(ToolSet.tools))
    result = await session.exec(statement)
    toolset = result.first()
    if not toolset:
        raise HTTPException(status_code=404, detail="Toolset not found")
    return toolset

async def load_assignable_toolsets(
    session: AsyncSession,
    toolset_ids: list[int],
    user_id: int,
) -> list[ToolSet]:
    if not toolset_ids:
        return []
    statement = (
        select(ToolSet)
        .where(ToolSet.id.in_(toolset_ids), toolset_visibility_filter(user_id))
        .options(selectinload(ToolSet.tools))
    )
    result = await session.exec(statement)
    toolsets = result.all()
    found = {t.id for t in toolsets}
    missing = set(toolset_ids) - found
    if missing:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "One or more toolsets do not exist or are not accessible",
                "toolset_ids": sorted(missing),
            },
        )
    return list(toolsets)

async def get_user_toolset_credential_row(
    session: AsyncSession,
    user_id: int,
    toolset_id: int,
) -> UserToolSetCredential | None:
    statement = select(UserToolSetCredential).where(
        UserToolSetCredential.user_id == user_id,
        UserToolSetCredential.toolset_id == toolset_id,
    )
    result = await session.exec(statement)
    return result.first()

async def user_has_toolset_credential(
    session: AsyncSession,
    user_id: int,
    toolset: ToolSet,
) -> bool:
    if not toolset.auth_required:
        return True
    row = await get_user_toolset_credential_row(session, user_id, toolset.id)
    return row is not None

async def get_user_toolset_token(
    session: AsyncSession,
    user_id: int,
    toolset: ToolSet,
) -> str | None:
    if not toolset.auth_required:
        return None
    row = await get_user_toolset_credential_row(session, user_id, toolset.id)
    if row is None:
        return None
    credential = await session.get(Credential, row.credential_id)
    if credential is None:
        return None
    if credential.user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail=f"Credential for toolset {toolset.id} does not belong to the current user",
        )
    return decrypt_token(credential.token)

async def set_user_toolset_credential(
    session: AsyncSession,
    user_id: int,
    toolset: ToolSet,
    token_plain: str,
) -> None:
    if not can_read_toolset(toolset, user_id):
        raise HTTPException(status_code=404, detail="Toolset not found")

    existing = await get_user_toolset_credential_row(session, user_id, toolset.id)
    if existing is not None:
        credential = await session.get(Credential, existing.credential_id)
        if credential is None:
            await session.delete(existing)
            await session.flush()
        else:
            if credential.user_id != user_id:
                raise HTTPException(status_code=403, detail="Credential does not belong to the current user")
            credential.token = encrypt_token(token_plain)
            session.add(credential)
            await session.commit()
            return

    credential = Credential(token=encrypt_token(token_plain), user_id=user_id)
    session.add(credential)
    await session.flush()
    link = UserToolSetCredential(
        user_id=user_id,
        toolset_id=toolset.id,
        credential_id=credential.id,
    )
    session.add(link)
    await session.commit()

async def attach_creator_credential_if_provided(
    session: AsyncSession,
    user_id: int,
    toolset: ToolSet,
    token_plain: str | None,
) -> None:
    if not token_plain:
        return
    await set_user_toolset_credential(session, user_id, toolset, token_plain)