import logging

from fastapi import APIRouter, Request, Depends, HTTPException
from sqlmodel import select
from sqlalchemy.orm import selectinload

from src.db.db import session_dep
from src.db.models import Tool, ToolPublic, ToolSetPublic, ToolSet, AgentToolSetLink, UserToolSetCredential
from lib.auth.auth import verify_token
from lib.auth.enums import Role

from lib.tool.models import CreateMCPToolSet, CreateHttpToolSet, SetToolSetCredential, ToolsResponse
from lib.tool.enums import ToolType
from lib.tool.http import get_tools
from lib.tool.access import (
    claims_from_request,
    toolset_visibility_filter,
    get_toolset_or_404,
    can_write_toolset,
    attach_creator_credential_if_provided,
    set_user_toolset_credential,
)
tool_router = APIRouter(prefix="/tool", dependencies=[Depends(verify_token)])
logger = logging.getLogger(__name__)


def _resolve_toolset_owner(shared: bool, user_id: int, role: Role) -> int | None:
    if shared:
        if role != Role.ADMIN:
            raise HTTPException(status_code=403, detail="Only admins can create shared toolsets")
        return None
    return user_id


@tool_router.get("/tools")
async def get_all_tools(request: Request, session: session_dep) -> dict[str, list[ToolPublic]]:
    user_id, _ = claims_from_request(request)
    statement = (
        select(Tool)
        .join(ToolSet, Tool.toolset_id == ToolSet.id)
        .where(toolset_visibility_filter(user_id))
    )
    result = await session.exec(statement)
    tools = result.all()
    return {"tools": [ToolPublic.model_validate(tool) for tool in tools]}


@tool_router.get("/toolsets")
async def get_all_toolsets(request: Request, session: session_dep) -> dict[str, list[ToolSetPublic]]:
    user_id, _ = claims_from_request(request)
    statement = (
        select(ToolSet)
        .where(toolset_visibility_filter(user_id))
        .options(selectinload(ToolSet.tools))
    )
    result = await session.exec(statement)
    toolsets = result.all()
    return {"toolsets": [ToolSetPublic.model_validate(toolset) for toolset in toolsets]}


@tool_router.get("/toolset/{id}")
async def get_toolset_by_id(request: Request, id: int, session: session_dep) -> dict[str, ToolSetPublic]:
    user_id, _ = claims_from_request(request)
    toolset = await get_toolset_or_404(session, id, user_id, load_tools=True)
    return {"toolset": ToolSetPublic.model_validate(toolset)}


@tool_router.put("/toolset/{id}/credential")
async def set_toolset_credential(
    request: Request,
    id: int,
    body: SetToolSetCredential,
    session: session_dep,
) -> dict[str, str]:
    user_id, _ = claims_from_request(request)
    toolset = await get_toolset_or_404(session, id, user_id)
    if not toolset.auth_required:
        raise HTTPException(status_code=400, detail="This toolset does not require authentication")
    await set_user_toolset_credential(session, user_id, toolset, body.token)
    return {"message": "Credential saved for toolset"}


@tool_router.post("/create/toolset/mcp")
async def create_mcp_toolset(
    request: Request, toolset: CreateMCPToolSet, session: session_dep
) -> dict[str, ToolSetPublic]:
    user_id, role = claims_from_request(request)
    owner_id = _resolve_toolset_owner(bool(toolset.shared), user_id, role)

    if toolset.auth_required and toolset.auth_type is None:
        raise HTTPException(status_code=400, detail="auth_type is required when auth_required is true")
    if toolset.auth_required and toolset.auth_type.value == "header" and not toolset.header:
        raise HTTPException(status_code=400, detail="header is required when auth_type is header")
    if owner_id is None and toolset.token:
        raise HTTPException(
            status_code=400,
            detail="Shared toolsets cannot store a token at creation; users configure credentials separately",
        )

    new_toolset = ToolSet(
        name=toolset.name,
        description=toolset.description,
        url=toolset.url,
        type=ToolType.MCP,
        auth_required=toolset.auth_required or False,
        auth_type=toolset.auth_type,
        header=toolset.header,
        user_id=owner_id,
    )
    session.add(new_toolset)
    await session.commit()
    await session.refresh(new_toolset)

    if owner_id is not None and toolset.token:
        await attach_creator_credential_if_provided(session, owner_id, new_toolset, toolset.token)

    if toolset.tools:
        for tool in toolset.tools:
            session.add(
                Tool(
                    name=tool,
                    description=f"Tool in {toolset.name} MCP toolset",
                    toolset_id=new_toolset.id,
                    type=ToolType.MCP,
                    url=new_toolset.url,
                )
            )
        await session.commit()

    loaded = await get_toolset_or_404(session, new_toolset.id, user_id, load_tools=True)
    return {"toolset": ToolSetPublic.model_validate(loaded)}


@tool_router.post("/create/toolset/http")
async def create_http_toolset(
    request: Request, toolset: CreateHttpToolSet, session: session_dep
) -> dict[str, ToolSetPublic]:
    user_id, role = claims_from_request(request)
    owner_id = _resolve_toolset_owner(bool(toolset.shared), user_id, role)

    token: str | None = None
    if toolset.auth_required and toolset.auth_type is None:
        raise HTTPException(status_code=400, detail="auth_type is required when auth_required is true")
    if toolset.auth_required and toolset.auth_type.value == "header" and not toolset.header:
        raise HTTPException(status_code=400, detail="header is required when auth_type is header")
    if owner_id is None and toolset.token:
        raise HTTPException(
            status_code=400,
            detail="Shared toolsets cannot store a token at creation; users configure credentials separately",
        )
    if owner_id is not None and toolset.token:
        token = toolset.token

    new_toolset = ToolSet(
        name=toolset.name,
        description=toolset.description,
        url=toolset.url,
        type=ToolType.HTTP,
        auth_required=toolset.auth_required or False,
        auth_type=toolset.auth_type,
        header=toolset.header,
        user_id=owner_id,
    )

    session.add(new_toolset)
    await session.commit()
    await session.refresh(new_toolset)

    if owner_id is not None and toolset.token:
        await attach_creator_credential_if_provided(session, owner_id, new_toolset, toolset.token)

    sync_token = token
    if sync_token is None and owner_id is not None and toolset.auth_required:
        sync_token = await _token_for_sync(session, owner_id, new_toolset)

    can_sync_tools = (not new_toolset.auth_required) or bool(sync_token)
    if can_sync_tools:
        tools = await get_tools(
            new_toolset.url,
            auth_required=new_toolset.auth_required,
            auth_type=new_toolset.auth_type,
            token=sync_token,
            header=new_toolset.header,
        )

        parsed_tools = ToolsResponse.model_validate(tools)

        for tool in parsed_tools.tools:
            session.add(
                Tool(
                    name=tool.name,
                    description=tool.description,
                    input=tool.input_schema,
                    toolset_id=new_toolset.id,
                    url=new_toolset.url,
                    type=ToolType.HTTP,
                )
            )

        await session.commit()

    loaded = await get_toolset_or_404(session, new_toolset.id, user_id, load_tools=True)
    return {"toolset": ToolSetPublic.model_validate(loaded)}


async def _token_for_sync(session, user_id: int, toolset: ToolSet) -> str | None:
    from lib.tool.access import get_user_toolset_token

    return await get_user_toolset_token(session, user_id, toolset)


@tool_router.get("/{id}")
async def get_tool_by_id(request: Request, id: int, session: session_dep) -> dict[str, ToolPublic]:
    user_id, _ = claims_from_request(request)
    tool = await session.get(Tool, id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    if tool.toolset_id is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    await get_toolset_or_404(session, tool.toolset_id, user_id)
    return {"tool": ToolPublic.model_validate(tool)}


@tool_router.delete("/toolset/{id}")
async def delete_toolset(request: Request, id: int, session: session_dep) -> dict[str, str]:
    user_id, role = claims_from_request(request)
    toolset = await session.get(ToolSet, id)
    if not toolset:
        raise HTTPException(status_code=404, detail="Toolset not found")
    if not can_write_toolset(toolset, user_id, role):
        raise HTTPException(status_code=403, detail="Not allowed to delete this toolset")

    statement = select(AgentToolSetLink).where(AgentToolSetLink.toolset_id == toolset.id)
    result = await session.exec(statement)
    for agent_toolset_link in result.all():
        await session.delete(agent_toolset_link)

    statement = select(UserToolSetCredential).where(UserToolSetCredential.toolset_id == toolset.id)
    result = await session.exec(statement)
    for link in result.all():
        await session.delete(link)

    statement = select(Tool).where(Tool.toolset_id == toolset.id)
    result = await session.exec(statement)
    for tool in result.all():
        await session.delete(tool)

    await session.delete(toolset)
    await session.commit()

    return {"message": "Toolset deleted successfully"}
