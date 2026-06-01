import logging

from typing import Annotated

from fastapi import APIRouter, Body, Request, Depends, HTTPException
from sqlmodel import select
from sqlalchemy.orm import selectinload

from src.db.db import session_dep
from src.db.models import Tool, ToolPublic, ToolSetPublic, ToolSet
from lib.auth.auth import verify_token

from lib.tool.models import (
    CreateMCPToolSet,
    CreateHttpToolSet,
    CreateLogicalToolSet,
    SetToolSetCredential,
    UpdateToolSet,
)
from lib.tool.enums import ToolType
from lib.tool.access import (
    _TOOLSET_LOAD_OPTIONS,
    claims_from_request,
    toolset_visibility_filter,
    get_toolset_or_404,
    can_write_toolset,
    attach_creator_credential_if_provided,
    set_user_toolset_credential,
    get_user_toolset_token,
)
from lib.tool.logical import dedupe_tools
from lib.tool.service import (
    validate_auth_fields,
    resolve_toolset_owner,
    sync_http_toolset_tools,
    replace_mcp_toolset_tools,
    replace_logical_toolset_members,
    delete_toolset_record,
)

tool_router = APIRouter(prefix="/tool", dependencies=[Depends(verify_token)])
logger = logging.getLogger(__name__)

@tool_router.get("/tools")
async def get_all_tools(request: Request, session: session_dep) -> dict[str, list[ToolPublic]]:
    user_id, _ = claims_from_request(request)
    statement = (
        select(Tool)
        .join(ToolSet, Tool.toolset_id == ToolSet.id)
        .where(
            toolset_visibility_filter(user_id),
            ToolSet.type != ToolType.LOGICAL,
        )
    )
    result = await session.exec(statement)
    tools = dedupe_tools(list(result.all()))
    tools.sort(key=lambda t: t.id or 0)
    return {"tools": [ToolPublic.model_validate(tool) for tool in tools]}

@tool_router.get("/toolsets")
async def get_all_toolsets(request: Request, session: session_dep) -> dict[str, list[ToolSetPublic]]:
    user_id, _ = claims_from_request(request)
    statement = (
        select(ToolSet)
        .where(toolset_visibility_filter(user_id))
        .options(*_TOOLSET_LOAD_OPTIONS)
    )
    result = await session.exec(statement)
    toolsets = result.all()
    return {"toolsets": [ToolSetPublic.model_validate(toolset) for toolset in toolsets]}

@tool_router.get("/toolset/{id}")
async def get_toolset_by_id(request: Request, id: int, session: session_dep) -> dict[str, ToolSetPublic]:
    user_id, _ = claims_from_request(request)
    toolset = await get_toolset_or_404(session, id, user_id, load_tools=True)
    return {"toolset": ToolSetPublic.model_validate(toolset)}

@tool_router.patch("/toolset/{id}")
async def update_toolset(
    request: Request,
    id: int,
    session: session_dep,
    body: Annotated[UpdateToolSet, Body(...)],
) -> dict[str, ToolSetPublic]:
    user_id, role = claims_from_request(request)
    toolset = await session.get(ToolSet, id)
    if not toolset:
        raise HTTPException(status_code=404, detail="Toolset not found")
    if not can_write_toolset(toolset, user_id, role):
        raise HTTPException(status_code=403, detail="Not allowed to update this toolset")

    updates = body.model_dump(exclude_unset=True)
    sync_tools = updates.pop("sync_tools", None)
    mcp_tools = updates.pop("tools", None)
    logical_tool_ids = updates.pop("tool_ids", None)

    if toolset.type == ToolType.LOGICAL:
        for key in ("url", "auth_required", "auth_type", "header"):
            updates.pop(key, None)
        if sync_tools or mcp_tools is not None:
            raise HTTPException(
                status_code=400,
                detail="Logical toolsets cannot sync remote tools; use tool_ids to set members",
            )

    for key, value in updates.items():
        setattr(toolset, key, value)

    if toolset.type != ToolType.LOGICAL:
        validate_auth_fields(toolset.auth_required, toolset.auth_type, toolset.header)

    if toolset.type == ToolType.HTTP and sync_tools:
        await sync_http_toolset_tools(session, toolset, user_id)
    elif toolset.type == ToolType.MCP and mcp_tools is not None:
        await replace_mcp_toolset_tools(session, toolset, mcp_tools)
    elif toolset.type == ToolType.LOGICAL and logical_tool_ids is not None:
        await replace_logical_toolset_members(session, toolset, logical_tool_ids, user_id)

    session.add(toolset)
    await session.commit()

    loaded = await get_toolset_or_404(session, toolset.id, user_id, load_tools=True)
    return {"toolset": ToolSetPublic.model_validate(loaded)}

@tool_router.put("/toolset/{id}/credential")
async def set_toolset_credential(
    request: Request,
    id: int,
    body: SetToolSetCredential,
    session: session_dep,
) -> dict[str, str]:
    user_id, _ = claims_from_request(request)
    toolset = await get_toolset_or_404(session, id, user_id)
    if toolset.type == ToolType.LOGICAL:
        raise HTTPException(status_code=400, detail="Logical toolsets do not use credentials")
    if not toolset.auth_required:
        raise HTTPException(status_code=400, detail="This toolset does not require authentication")
    await set_user_toolset_credential(session, user_id, toolset, body.token)
    return {"message": "Credential saved for toolset"}

@tool_router.post("/create/toolset/mcp")
async def create_mcp_toolset(
    request: Request, toolset: CreateMCPToolSet, session: session_dep
) -> dict[str, ToolSetPublic]:
    user_id, role = claims_from_request(request)
    owner_id = resolve_toolset_owner(bool(toolset.shared), user_id, role)

    validate_auth_fields(toolset.auth_required or False, toolset.auth_type, toolset.header)
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
        await replace_mcp_toolset_tools(session, new_toolset, toolset.tools)
        await session.commit()

    loaded = await get_toolset_or_404(session, new_toolset.id, user_id, load_tools=True)
    return {"toolset": ToolSetPublic.model_validate(loaded)}

@tool_router.post("/create/toolset/http")
async def create_http_toolset(
    request: Request, toolset: CreateHttpToolSet, session: session_dep
) -> dict[str, ToolSetPublic]:
    user_id, role = claims_from_request(request)
    owner_id = resolve_toolset_owner(bool(toolset.shared), user_id, role)

    validate_auth_fields(toolset.auth_required or False, toolset.auth_type, toolset.header)
    if owner_id is None and toolset.token:
        raise HTTPException(
            status_code=400,
            detail="Shared toolsets cannot store a token at creation; users configure credentials separately",
        )

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

    sync_token = toolset.token
    if sync_token is None and owner_id is not None and toolset.auth_required:
        sync_token = await get_user_toolset_token(session, owner_id, new_toolset)

    can_sync_tools = (not new_toolset.auth_required) or bool(sync_token)
    if can_sync_tools:
        await sync_http_toolset_tools(session, new_toolset, user_id, token=sync_token)
        await session.commit()

    loaded = await get_toolset_or_404(session, new_toolset.id, user_id, load_tools=True)
    return {"toolset": ToolSetPublic.model_validate(loaded)}

@tool_router.post("/create/toolset/logical")
async def create_logical_toolset(
    request: Request, toolset: CreateLogicalToolSet, session: session_dep
) -> dict[str, ToolSetPublic]:
    user_id, role = claims_from_request(request)
    owner_id = resolve_toolset_owner(bool(toolset.shared), user_id, role)

    new_toolset = ToolSet(
        name=toolset.name,
        description=toolset.description,
        url="",
        type=ToolType.LOGICAL,
        auth_required=False,
        auth_type=None,
        header=None,
        user_id=owner_id,
    )
    session.add(new_toolset)
    await session.commit()
    await session.refresh(new_toolset)

    if toolset.tool_ids:
        await replace_logical_toolset_members(session, new_toolset, toolset.tool_ids, user_id)
        await session.commit()

    loaded = await get_toolset_or_404(session, new_toolset.id, user_id, load_tools=True)
    return {"toolset": ToolSetPublic.model_validate(loaded)}

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

    await delete_toolset_record(session, toolset)
    return {"message": "Toolset deleted successfully"}
