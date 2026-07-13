from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from lib.auth.enums import Role
from lib.tool.enums import AuthType, ToolType
from lib.tool.http import get_tools
from lib.tool.models import ToolsResponse
from lib.tool.access import get_user_toolset_token, load_assignable_tools
from src.db.models import (
    Tool,
    ToolSet,
    AgentToolSetLink,
    AgentToolLink,
    ToolSetToolLink,
    UserToolSetCredential,
    Credential,
)

def validate_auth_fields(
    auth_required: bool,
    auth_type: AuthType | None,
    header: str | None,
) -> None:
    if auth_required and auth_type is None:
        raise HTTPException(status_code=400, detail="auth_type is required when auth_required is true")
    if auth_required and auth_type is not None and auth_type.value == "header" and not header:
        raise HTTPException(status_code=400, detail="header is required when auth_type is header")

def resolve_toolset_owner(shared: bool, user_id: int, role: Role) -> int | None:
    if shared:
        if role != Role.ADMIN:
            raise HTTPException(status_code=403, detail="Only admins can create shared toolsets")
        return None
    return user_id

async def _delete_tool_membership_links(session: AsyncSession, tool_ids: list[int]) -> None:
    if not tool_ids:
        return
    statement = select(ToolSetToolLink).where(ToolSetToolLink.tool_id.in_(tool_ids))
    result = await session.exec(statement)
    for link in result.all():
        await session.delete(link)

async def delete_toolset_tools(session: AsyncSession, toolset_id: int) -> None:
    statement = select(Tool).where(Tool.toolset_id == toolset_id)
    result = await session.exec(statement)
    tools = result.all()
    tool_ids = [tool.id for tool in tools if tool.id is not None]
    await _delete_tool_membership_links(session, tool_ids)
    for tool in tools:
        await session.delete(tool)

async def sync_http_toolset_tools(
    session: AsyncSession,
    toolset: ToolSet,
    user_id: int,
    *,
    token: str | None = None,
) -> None:
    if token is None:
        token = await get_user_toolset_token(session, user_id, toolset)
    if toolset.auth_required and not token:
        raise HTTPException(
            status_code=400,
            detail="Cannot sync tools: configure your credential via PUT /tool/toolset/{id}/credential",
        )
    tools = await get_tools(
        toolset.url,
        auth_required=toolset.auth_required,
        auth_type=toolset.auth_type,
        token=token,
        header=toolset.header,
    )
    parsed = ToolsResponse.model_validate(tools)
    await delete_toolset_tools(session, toolset.id)
    for tool in parsed.tools:
        session.add(
            Tool(
                name=tool.name,
                description=tool.description,
                input=tool.input_schema,
                toolset_id=toolset.id,
                url=toolset.url,
                type=ToolType.HTTP,
            )
        )

async def replace_mcp_toolset_tools(
    session: AsyncSession,
    toolset: ToolSet,
    tool_names: list[str],
) -> None:
    await delete_toolset_tools(session, toolset.id)
    for name in tool_names:
        session.add(
            Tool(
                name=name,
                description=f"Tool in {toolset.name} MCP toolset",
                toolset_id=toolset.id,
                type=ToolType.MCP,
                url=toolset.url,
            )
        )

async def replace_logical_toolset_members(
    session: AsyncSession,
    toolset: ToolSet,
    tool_ids: list[int],
    user_id: int,
) -> None:
    tools = await load_assignable_tools(session, tool_ids, user_id)
    statement = select(ToolSetToolLink).where(ToolSetToolLink.toolset_id == toolset.id)
    result = await session.exec(statement)
    for link in result.all():
        await session.delete(link)
    for tool in tools:
        if tool.id is None:
            continue
        session.add(ToolSetToolLink(toolset_id=toolset.id, tool_id=tool.id))

async def delete_logical_toolset_links(session: AsyncSession, toolset_id: int) -> None:
    statement = select(ToolSetToolLink).where(ToolSetToolLink.toolset_id == toolset_id)
    result = await session.exec(statement)
    for link in result.all():
        await session.delete(link)


async def delete_toolset_user_credentials(session: AsyncSession, toolset_id: int) -> None:
    statement = select(UserToolSetCredential).where(
        UserToolSetCredential.toolset_id == toolset_id
    )
    result = await session.exec(statement)
    rows = result.all()
    credential_ids = [row.credential_id for row in rows]

    for row in rows:
        await session.delete(row)
    await session.flush()

    for credential_id in credential_ids:
        other_links = await session.exec(
            select(UserToolSetCredential).where(
                UserToolSetCredential.credential_id == credential_id
            )
        )
        if other_links.first() is not None:
            continue
        credential = await session.get(Credential, credential_id)
        if credential is not None:
            await session.delete(credential)

    await session.flush()


async def delete_toolset_record(session: AsyncSession, toolset: ToolSet, *, commit: bool = True) -> None:
    statement = select(AgentToolSetLink).where(AgentToolSetLink.toolset_id == toolset.id)
    result = await session.exec(statement)
    for link in result.all():
        await session.delete(link)

    if toolset.type == ToolType.LOGICAL:
        await delete_logical_toolset_links(session, toolset.id)
    else:
        statement = select(Tool).where(Tool.toolset_id == toolset.id)
        result = await session.exec(statement)
        tool_ids = [tool.id for tool in result.all() if tool.id is not None]
        if tool_ids:
            statement = select(AgentToolLink).where(AgentToolLink.tool_id.in_(tool_ids))
            result = await session.exec(statement)
            for link in result.all():
                await session.delete(link)
        await delete_toolset_tools(session, toolset.id)

    await delete_toolset_user_credentials(session, toolset.id)
    await session.flush()
    await session.delete(toolset)
    if commit:
        await session.commit()
