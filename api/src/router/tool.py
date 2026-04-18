import logging

from fastapi import APIRouter, Request, Depends, HTTPException
from sqlmodel import select
from sqlalchemy.orm import selectinload

from src.db.db import session_dep
from src.db.models import Tool, ToolPublic, ToolSetPublic, ToolSet, AgentToolSetLink
from lib.auth.auth import verify_token

from lib.tool.models import CreateMCPToolSet, CreateHttpToolSet
from lib.tool.enums import ToolType
from lib.tool.models import ToolsResponse
from lib.tool.http import get_tools

tool_router = APIRouter(prefix="/tool", dependencies=[Depends(verify_token)])
logger = logging.getLogger(__name__)

@tool_router.get("/tools")
async def get_all_tools(session: session_dep) -> dict[str, list[ToolPublic]]:
    statement = select(Tool)
    result = await session.exec(statement)
    tools = result.all()
    return {"tools": [ToolPublic.model_validate(tool) for tool in tools]}

@tool_router.get("/toolsets")
async def get_all_toolsets(session: session_dep) -> dict[str, list[ToolSetPublic]]:
    statement = select(ToolSet).options(selectinload(ToolSet.tools))
    result = await session.exec(statement)
    toolsets = result.all()
    return {"toolsets": [ToolSetPublic.model_validate(toolset) for toolset in toolsets]}

@tool_router.get("/toolset/{id}")
async def get_toolset_by_id(id: int, session: session_dep) -> dict[str, ToolSetPublic]:
    statement = (
        select(ToolSet)
        .where(ToolSet.id == id)
        .options(selectinload(ToolSet.tools))
    )
    result = await session.exec(statement)
    toolset = result.one_or_none()
    if not toolset:
        raise HTTPException(status_code=404, detail="Toolset not found")
    return {"toolset": ToolSetPublic.model_validate(toolset)}

@tool_router.post("/create/toolset/mcp")
async def create_mcp_toolset(toolset: CreateMCPToolSet, session: session_dep) -> dict[str, ToolSetPublic]:
    new_toolset = ToolSet(name=toolset.name, description=toolset.description, url=toolset.url, type=ToolType.MCP, **({"tools": toolset.tools} if toolset.tools is not None else {}))
    session.add(new_toolset)
    await session.commit()
    await session.refresh(new_toolset)

    if toolset.tools:
        for tool in toolset.tools:
            session.add(
                Tool(
                    name=tool,
                    description=f"Tool in {toolset.name} MCP toolset",
                    toolset_id=new_toolset.id,
                    type=ToolType.MCP,
                    url=new_toolset.url
                )
            )

        await session.commit()

    statement = (
        select(ToolSet)
        .where(ToolSet.id == new_toolset.id)
        .options(selectinload(ToolSet.tools))
    )

    result = await session.exec(statement)
    loaded = result.one()
    return {"toolset": ToolSetPublic.model_validate(loaded)}

@tool_router.post("/create/toolset/http")
async def create_http_toolset(toolset: CreateHttpToolSet, session: session_dep) -> dict[str, ToolSetPublic]:
    new_toolset = ToolSet(name=toolset.name, description=toolset.description, url=toolset.url, type=ToolType.HTTP)

    session.add(new_toolset)
    await session.commit()
    await session.refresh(new_toolset)

    tools = await get_tools(new_toolset.url)

    parsed_tools = ToolsResponse.model_validate(tools)

    for tool in parsed_tools.tools:
        session.add(
            Tool(
                name=tool.name,
                description=tool.description,
                input=tool.input_schema,
                toolset_id=new_toolset.id,
                url=new_toolset.url,
                type=ToolType.HTTP
            )
        )

    await session.commit()

    statement = (
        select(ToolSet)
        .where(ToolSet.id == new_toolset.id)
        .options(selectinload(ToolSet.tools))
    )
    result = await session.exec(statement)
    loaded = result.one()
    return {"toolset": ToolSetPublic.model_validate(loaded)}

@tool_router.get("/{id}")
async def get_tool_by_id(id: int, session: session_dep) -> dict[str, ToolPublic]:
    tool = await session.get(Tool, id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return {"tool": ToolPublic.model_validate(tool)}

@tool_router.delete("/toolset/{id}")
async def delete_toolset(id: int, session: session_dep) -> dict[str, str]:
    statement = select(ToolSet).where(ToolSet.id == id)
    result = await session.exec(statement)
    toolset = result.first()

    if not toolset:
        raise HTTPException(status_code=404, detail="Toolset not found")

    statement = select(AgentToolSetLink).where(AgentToolSetLink.toolset_id == toolset.id)
    result = await session.exec(statement)
    agent_toolset_links = result.all()
    for agent_toolset_link in agent_toolset_links:
        await session.delete(agent_toolset_link)

    statement = select(Tool).where(Tool.toolset_id == toolset.id)
    result = await session.exec(statement)
    tools = result.all()
    for tool in tools:
        await session.delete(tool)

    await session.delete(toolset)
    await session.commit()

    return {"message": "Toolset deleted successfully"}
