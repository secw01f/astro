import logging

from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import selectinload
from sqlmodel import select

from src.db.db import session_dep
from src.db.models import Agent, AgentPublic, LLM, Prompt, Tool
from lib.auth.auth import verify_token

from lib.agent.enums import AgentRole
from lib.agent.models import (
    CreateAgent,
    UpdateAgent,
    UpdatePrompt,
    validate_agent_configuration,
)
from lib.tool import validate_toolsets_ready_for_agent, validate_tools_ready_for_agent
from lib.tool.access import (
    claims_from_request,
    load_assignable_toolsets,
    load_assignable_tools,
    _TOOLSET_LOAD_OPTIONS,
)

agent_router = APIRouter(prefix="/agent", dependencies=[Depends(verify_token)])
logger = logging.getLogger(__name__)

_AGENT_LOAD_OPTIONS = (
    selectinload(Agent.stacks),
    selectinload(Agent.toolsets).options(*_TOOLSET_LOAD_OPTIONS),
    selectinload(Agent.tools).selectinload(Tool.toolset),
    selectinload(Agent.llm),
)

@agent_router.get("/agents")
async def get_all_agents(request: Request, session: session_dep) -> dict[str, list[AgentPublic]]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    statement = (
        select(Agent)
        .where(Agent.user_id == user_id)
        .options(*_AGENT_LOAD_OPTIONS)
    )
    result = await session.exec(statement)
    agents = result.all()
    return {"agents": [AgentPublic.model_validate(agent) for agent in agents]}

@agent_router.get("/prompts")
async def get_prebuilt_prompts(session: session_dep) -> dict[str, list[Prompt]]:
    stmt = select(Prompt)
    result = await session.exec(stmt)
    prompts = result.all()
    return {"prompts": [Prompt.model_validate(prompt) for prompt in prompts]}

@agent_router.patch("/prompt/{id}")
async def update_prebuilt_prompt(id: int, body: UpdatePrompt, session: session_dep) -> dict[str, Prompt]:
    stmt = select(Prompt).where(Prompt.id == id)
    result = await session.exec(stmt)
    prompt = result.first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    prompt.prompt = body.prompt
    session.add(prompt)
    await session.flush()
    await session.commit()
    await session.refresh(prompt)
    return {"prompt": Prompt.model_validate(prompt)}

@agent_router.get("/{id}")
async def get_agent_by_id(request: Request, id: int, session: session_dep) -> dict[str, AgentPublic]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    statement = (
        select(Agent)
        .where(Agent.user_id == user_id, Agent.id == id)
        .options(*_AGENT_LOAD_OPTIONS)
    )
    result = await session.exec(statement)
    agent = result.first()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return {"agent": AgentPublic.model_validate(agent)}

@agent_router.patch("/{id}")
async def update_agent(request: Request, id: int, body: UpdateAgent, session: session_dep) -> dict[str, AgentPublic]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    statement = (
        select(Agent)
        .where(Agent.user_id == user_id, Agent.id == id)
        .options(selectinload(Agent.toolsets).options(*_TOOLSET_LOAD_OPTIONS), selectinload(Agent.tools))
    )
    result = await session.exec(statement)
    agent = result.first()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    updates = body.model_dump(exclude_unset=True)
    if "type" in updates:
        agent.agent_type = updates.pop("type")
    if "llm" in updates:
        llm_id = updates.pop("llm")
        llm = await session.get(LLM, llm_id)
        if llm is None or llm.user_id != user_id:
            raise HTTPException(status_code=404, detail="LLM not found")
        agent.llm_id = llm_id
    toolset_ids = updates.pop("toolset_ids", None)
    tool_ids = updates.pop("tool_ids", None)
    for key, value in updates.items():
        setattr(agent, key, value)

    if toolset_ids is not None:
        if not toolset_ids:
            agent.toolsets = []
        else:
            toolsets = await load_assignable_toolsets(session, toolset_ids, user_id)
            await validate_toolsets_ready_for_agent(session, user_id, toolsets)
            agent.toolsets = toolsets

    if tool_ids is not None:
        if not tool_ids:
            agent.tools = []
        else:
            tools = await load_assignable_tools(session, tool_ids, user_id)
            await validate_tools_ready_for_agent(session, user_id, tools)
            agent.tools = tools

    try:
        validate_agent_configuration(
            agent.agent_type,
            agent.role,
            [toolset.id for toolset in agent.toolsets or [] if toolset.id is not None],
            [tool.id for tool in agent.tools or [] if tool.id is not None],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session.add(agent)
    await session.flush()
    await session.commit()

    loaded_stmt = (
        select(Agent)
        .where(Agent.id == agent.id, Agent.user_id == user_id)
        .options(*_AGENT_LOAD_OPTIONS)
    )
    loaded = (await session.exec(loaded_stmt)).one()
    return {"agent": AgentPublic.model_validate(loaded)}

@agent_router.post("/create")
async def create_agent(request: Request, agent: CreateAgent, session: session_dep) -> dict[str, AgentPublic]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    llm = await session.get(LLM, agent.llm)
    if llm is None or llm.user_id != user_id:
        raise HTTPException(status_code=404, detail="LLM not found")

    system_prompt = agent.system_prompt
    if system_prompt is None and agent.role not in (
        AgentRole.CUSTOM_SUPERVISOR,
        AgentRole.CUSTOM_SUPPORTING_AGENT,
    ):
        stmt = select(Prompt).where(Prompt.role == agent.role)
        result = await session.exec(stmt)
        prebuilt = result.first()
        if prebuilt:
            system_prompt = prebuilt.prompt

    new_agent = Agent(
        name=agent.name,
        description=agent.description,
        system_prompt=system_prompt or "",
        llm_id=agent.llm,
        agent_type=agent.type,
        role=agent.role,
        user_id=user_id,
    )

    ids = agent.toolset_ids or []
    if ids:
        toolsets = await load_assignable_toolsets(session, ids, user_id)
        await validate_toolsets_ready_for_agent(session, user_id, toolsets)
        new_agent.toolsets = toolsets

    tool_ids = agent.tool_ids or []
    if tool_ids:
        tools = await load_assignable_tools(session, tool_ids, user_id)
        await validate_tools_ready_for_agent(session, user_id, tools)
        new_agent.tools = tools

    session.add(new_agent)
    await session.flush()
    await session.commit()

    loaded_stmt = (
        select(Agent)
        .where(Agent.id == new_agent.id, Agent.user_id == user_id)
        .options(*_AGENT_LOAD_OPTIONS)
    )
    loaded = (await session.exec(loaded_stmt)).one()
    return {"agent": AgentPublic.model_validate(loaded)}

@agent_router.delete("/{id}")
async def delete_agent(request: Request, id: int, session: session_dep) -> dict[str, str]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    statement = select(Agent).where(Agent.user_id == user_id, Agent.id == id)
    result = await session.exec(statement)
    agent = result.first()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    await session.delete(agent)
    await session.commit()

    return {"message": "Agent deleted successfully"}
