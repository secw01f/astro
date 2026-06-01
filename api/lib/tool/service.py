from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from lib.auth.enums import Role
from lib.tool.enums import AuthType, ToolType
from lib.tool.http import get_tools
from lib.tool.models import ToolsResponse
from lib.tool.access import get_user_toolset_token
from src.db.models import Tool, ToolSet, AgentToolSetLink, UserToolSetCredential

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

async def delete_toolset_tools(session: AsyncSession, toolset_id: int) -> None:
    statement = select(Tool).where(Tool.toolset_id == toolset_id)
    result = await session.exec(statement)
    for tool in result.all():
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

async def delete_toolset_record(session: AsyncSession, toolset: ToolSet) -> None:
    statement = select(AgentToolSetLink).where(AgentToolSetLink.toolset_id == toolset.id)
    result = await session.exec(statement)
    for link in result.all():
        await session.delete(link)

    statement = select(UserToolSetCredential).where(UserToolSetCredential.toolset_id == toolset.id)
    result = await session.exec(statement)
    for link in result.all():
        await session.delete(link)

    await delete_toolset_tools(session, toolset.id)
    await session.delete(toolset)
    await session.commit()