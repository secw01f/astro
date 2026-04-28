import logging
import asyncio
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlmodel import select
from sqlalchemy.orm import noload, selectinload
from typing import Annotated
from haystack.dataclasses import ChatMessage, ChatRole

from src.db.db import async_session, session_dep
from src.db.models import LLM, Agent, Stack, StackPublic, Message, ToolSet, AgentStackLink, Credential
from lib.auth.auth import verify_token

from lib.agent import SupervisorAgent, SupportingAgent, StreamingCallback
from lib.message import event_stream, fanout, storage_consumer, next_position
from lib.stack.models import CreateStack, ExecuteStack, UpdateStack
from lib.agent.enums import AgentType
from lib.agent.prompts import create_prompt
from lib.llm import chat_generator
from lib.credentials import decrypt_token
from lib.tool.enums import ToolType
from lib.tool.mcp import MCP, is_valid_server
from lib.tool.http import http_toolset_factory
from src.tool.memory import MemoryToolset
from src.tool.date import DateToolset
from src.tool.math import MathToolset
from src.tool.spec import SpecToolset
from src.tool.message import MessageToolset

stack_router = APIRouter(prefix="/stack", dependencies=[Depends(verify_token)])
logger = logging.getLogger(__name__)

@stack_router.get("/stacks")
async def get_all_stacks(request: Request, session: session_dep) -> dict[str, list[StackPublic]]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    statement = (
        select(Stack)
        .options(
            selectinload(Stack.agents).options(
                selectinload(Agent.llm),
                selectinload(Agent.toolsets).selectinload(ToolSet.tools),
                selectinload(Agent.stacks).selectinload(Stack.agents).options(
                    selectinload(Agent.llm),
                    selectinload(Agent.toolsets).selectinload(ToolSet.tools),
                    noload(Agent.stacks),
                ),
            ),
        )
        .where(Stack.user_id == user_id)
    )
    result = await session.exec(statement)
    stacks = result.all()

    return {"stacks": [StackPublic.model_validate(stack) for stack in stacks]}

@stack_router.get("/{id}")
async def get_stack_by_id(request: Request, id: int, session: session_dep) -> dict[str, StackPublic]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    statement = (
        select(Stack)
        .options(
            selectinload(Stack.agents).options(
                selectinload(Agent.llm),
                selectinload(Agent.toolsets).selectinload(ToolSet.tools),
                selectinload(Agent.stacks).selectinload(Stack.agents).options(
                    selectinload(Agent.llm),
                    selectinload(Agent.toolsets).selectinload(ToolSet.tools),
                    noload(Agent.stacks),
                ),
            ),
        )
        .where(Stack.id == id, Stack.user_id == user_id)
    )
    result = await session.exec(statement)
    stack = result.first()

    if not stack:
        raise HTTPException(status_code=404, detail="Stack not found")

    return {"stack": StackPublic.model_validate(stack)}

@stack_router.post("/create")
async def create_stack(request: Request, stack: CreateStack, session: session_dep) -> dict[str, StackPublic]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    supporting_ids = list(dict.fromkeys(stack.supporting))
    requested_ids = [stack.supervisor, *supporting_ids]
    all_agent_ids = list(dict.fromkeys(requested_ids))

    if not all_agent_ids:
        raise HTTPException(status_code=400, detail="A supervisor and at least one supporting agent are required")

    statement = select(Agent).where(Agent.id.in_(all_agent_ids))
    result = await session.exec(statement)
    all_agents = result.all()
    all_by_id = {agent.id: agent for agent in all_agents if agent.id is not None}

    missing_ids = [agent_id for agent_id in all_agent_ids if agent_id not in all_by_id]
    if missing_ids:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "One or more agents do not exist",
                "agent_ids": missing_ids,
            },
        )

    supervisor_agent = all_by_id[stack.supervisor]
    if supervisor_agent.agent_type != AgentType.SUPERVISOR:
        raise HTTPException(status_code=400, detail="Supervisor agent must have type 'supervisor'")

    supporting_agents = [all_by_id[agent_id] for agent_id in supporting_ids]
    wrong_supporting = [a.id for a in supporting_agents if a.agent_type != AgentType.SUPPORTING]
    if wrong_supporting:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Supporting agents must have type 'supporting'",
                "agent_ids": wrong_supporting,
            },
        )

    _stack = Stack(name=stack.name, description=stack.description, user_id=user_id)
    _stack.agents = [supervisor_agent, *supporting_agents]
    session.add(_stack)

    await session.commit()
    statement = (
        select(Stack)
        .options(
            selectinload(Stack.agents).options(
                selectinload(Agent.llm),
                selectinload(Agent.toolsets).selectinload(ToolSet.tools),
                selectinload(Agent.stacks).selectinload(Stack.agents).options(
                    selectinload(Agent.llm),
                    selectinload(Agent.toolsets).selectinload(ToolSet.tools),
                    noload(Agent.stacks),
                ),
            ),
        )
        .where(Stack.id == _stack.id, Stack.user_id == user_id)
    )
    reload_result = await session.exec(statement)
    loaded = reload_result.first()
    if not loaded:
        raise HTTPException(status_code=404, detail="Stack not found")
    return {"stack": StackPublic.model_validate(loaded)}

@stack_router.patch("/{id}")
async def update_stack(request: Request, id: int, stack: Annotated[UpdateStack, Body(...)], session: session_dep) -> dict[str, StackPublic]:
    claims = getattr(request.state, "claims", None)
    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]
    
    statement = select(Stack).where(Stack.id == id, Stack.user_id == user_id)
    result = await session.exec(statement)
    existing_stack = result.first()
    if not existing_stack:
        raise HTTPException(status_code=404, detail="Stack not found")

    updates = stack.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(existing_stack, key, value)
    await session.commit()
    statement = (
        select(Stack)
        .options(
            selectinload(Stack.agents).options(
                selectinload(Agent.llm),
                selectinload(Agent.toolsets).selectinload(ToolSet.tools),
                selectinload(Agent.stacks).selectinload(Stack.agents).options(
                    selectinload(Agent.llm),
                    selectinload(Agent.toolsets).selectinload(ToolSet.tools),
                    noload(Agent.stacks),
                ),
            ),
        )
        .where(Stack.id == id, Stack.user_id == user_id)
    )
    reload_result = await session.exec(statement)
    loaded = reload_result.first()
    if not loaded:
        raise HTTPException(status_code=404, detail="Stack not found")
    return {"stack": StackPublic.model_validate(loaded)}

@stack_router.post("/{id}/exec")
async def run_stack(request: Request, id: int, execute: ExecuteStack, session: session_dep):
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    _stack_statement = (
        select(Stack)
        .options(
            selectinload(Stack.agents)
            .selectinload(Agent.toolsets)
            .selectinload(ToolSet.tools)
        )
        .where(Stack.id == id, Stack.user_id == user_id)
    )
    _stack_result = await session.exec(_stack_statement)
    _stack = _stack_result.first()

    if not _stack:
        raise HTTPException(status_code=404, detail="Stack not found")

    _supervisors = [agent for agent in _stack.agents if agent.agent_type == AgentType.SUPERVISOR]
    if len(_supervisors) == 0:
        raise HTTPException(status_code=400, detail="Stack has no supervisor agent")
    _stack_supervisor = _supervisors[0]

    if _stack_supervisor.llm_id is None:
        raise HTTPException(status_code=400, detail="Supervisor agent is missing an LLM")
    _supervisor_llm = await session.get(LLM, _stack_supervisor.llm_id)
    if _supervisor_llm is None:
        raise HTTPException(status_code=404, detail="Supervisor LLM not found")

    _credential = await session.get(Credential, _supervisor_llm.credential_id)
    if _credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    _token = decrypt_token(_credential.token)

    supervisor_llm = chat_generator(_supervisor_llm.provider, _supervisor_llm.model, _token, _supervisor_llm.key_id, _supervisor_llm.region, _supervisor_llm.max_tokens)
    
    run_id = str(uuid.uuid4())

    main_queue = asyncio.Queue()
    client_queue = asyncio.Queue()
    storage_queue = asyncio.Queue()

    _app_loop = asyncio.get_running_loop()
    _callback = StreamingCallback(
        _stack_supervisor.name,
        main_queue,
        run_id,
        loop=_app_loop,
    )

    supervisor = SupervisorAgent(
        chat_generator=supervisor_llm,
        system_prompt=create_prompt(_stack_supervisor.system_prompt, AgentType.SUPERVISOR),
        streaming_callback=_callback
    )

    supervisor.add_tool(MemoryToolset(user_id, app_loop=_app_loop))
    supervisor.add_tool(DateToolset())
    supervisor.add_tool(MathToolset())
    supervisor.add_tool(SpecToolset())
    supervisor.add_tool(MessageToolset(id, app_loop=_app_loop))

    _stack_agents = [agent for agent in _stack.agents if agent.agent_type == AgentType.SUPPORTING]

    for agent in _stack_agents:
        if agent.llm_id is None:
            raise HTTPException(status_code=400, detail=f"Supporting agent {agent.id} is missing an LLM")
        _llm = await session.get(LLM, agent.llm_id)
        if _llm is None:
            raise HTTPException(status_code=404, detail=f"LLM {agent.llm_id} for supporting agent {agent.id} not found")

        _credential = await session.get(Credential, _llm.credential_id)
        if _credential is None:
            raise HTTPException(status_code=404, detail=f"Credential {_llm.credential_id} for LLM {agent.llm_id} not found")
        _token = decrypt_token(_credential.token)

        _agent_llm = chat_generator(_llm.provider, _llm.model, _token, _llm.key_id, _llm.region, _llm.max_tokens)

        _agent_tools = [MemoryToolset(user_id, app_loop=_app_loop), DateToolset(), MathToolset(), SpecToolset()]

        for toolset in agent.toolsets:
            if toolset.credential_id is not None:
                _credential = await session.get(Credential, toolset.credential_id)
                if _credential is None:
                    raise HTTPException(status_code=404, detail=f"Credential {toolset.credential_id} for toolset {toolset.id} not found")
                token = decrypt_token(_credential.token)
            else:
                token = None
            if toolset.type == ToolType.MCP:
                if toolset.auth_required and toolset.credential_id is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"MCP toolset {toolset.id} requires a credential but none is configured",
                    )
                tools = []
                auth_required = toolset.auth_required
                auth_type = toolset.auth_type
                header = toolset.header
                if toolset.tools != None:
                    for tool in toolset.tools:
                        tools.append(tool.name)
                if len(tools) != 0:
                    try:
                        if is_valid_server(toolset.url, auth_required, auth_type, token, header):
                            _agent_tools.append(MCP(toolset.url, tools, auth_required, auth_type, token, header))
                        else:
                            logger.error(f"Invalid MCP server: {toolset.url}")
                            pass
                    except Exception as e:
                        logger.error(f"Error adding MCP toolset {toolset.url}: {e}")
                        pass
                else:
                    try:
                        if is_valid_server(toolset.url, auth_required, auth_type, token, header):
                            _agent_tools.append(
                                MCP(
                                    toolset.url,
                                    auth_required=auth_required,
                                    auth_type=auth_type,
                                    token=token,
                                    header=header,
                                )
                            )
                        else:
                            logger.error(f"Invalid MCP server: {toolset.url}")
                            pass
                    except Exception as e:
                        logger.error(f"Error adding MCP toolset {toolset.url}: {e}")
                        pass

            elif toolset.type == ToolType.HTTP:
                if toolset.auth_required and toolset.credential_id is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"HTTP toolset {toolset.id} requires a credential but none is configured",
                    )
                _http_toolset = http_toolset_factory(toolset, toolset.tools, token=token)
                _agent_tools.append(_http_toolset)

        _support_stream = StreamingCallback(
            agent.name,
            main_queue,
            run_id,
            loop=_app_loop,
        )
        _agent = SupportingAgent(
            chat_generator=_agent_llm,
            name=agent.name,
            description=agent.description,
            system_prompt=create_prompt(agent.system_prompt, AgentType.SUPPORTING),
            user_prompt="""{% message role="user" %}{{prompt}}{% endmessage %}""",
            required_variables=["prompt"],
            tools=_agent_tools,
            streaming_callback=_support_stream,
        )

        supervisor.register_supporting_agent(_agent)

    supervisor.warm_up()

    _position = await next_position(session, id, user_id)

    user_message = Message(
        role="user",
        content=execute.message,
        position=_position,
        stack_id=id
    )

    session.add(user_message)
    await session.commit()

    assistant_position_state = {"next": _position + 1}

    async def storage_worker():
        async with async_session() as storage_session:
            await storage_consumer(storage_queue, storage_session, id, assistant_position_state)

    async def fanout_worker():
        await fanout(
            main_queue,
            client_queue,
            storage_queue,
            verbose=execute.verbose,
            supervisor_agent_name=_stack_supervisor.name,
        )

    async def runner():
        fanout_task = asyncio.create_task(fanout_worker())
        storage_task = asyncio.create_task(storage_worker())
        try:
            messages_for_run = [ChatMessage.from_user(execute.message)]
            result = await asyncio.to_thread(supervisor.run, messages=messages_for_run)

            await asyncio.sleep(0)

            final_text = None
            for msg in reversed((result or {}).get("messages") or []):
                if msg.is_from(ChatRole.ASSISTANT) and msg.text:
                    final_text = msg.text
                    break
            _callback.emit_final_assistant_text(final_text)
        except Exception as e:
            logger.exception("Stack run failed", exc_info=e)
            _callback.emit_final_assistant_text(
                f"Stack execution failed: {str(e)}"
            )
        finally:
            _callback.end()
            await asyncio.sleep(0)
            await main_queue.put(None)
            await fanout_task
            await storage_task

    asyncio.create_task(runner())

    return StreamingResponse(
        event_stream(client_queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@stack_router.delete("/{id}")
async def delete_stack(request: Request, id: int, session: session_dep) -> dict[str, str]:
    claims = getattr(request.state, "claims", None)

    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]

    statement = select(Stack).where(Stack.id == id, Stack.user_id == user_id)
    result = await session.exec(statement)
    stack = result.first()

    if not stack:
        raise HTTPException(status_code=404, detail="Stack not found")

    statement = select(Message).where(Message.stack_id == id)
    result = await session.exec(statement)
    messages = result.all()
    for message in messages:
        await session.delete(message)

    statement = select(AgentStackLink).where(AgentStackLink.stack_id == id)
    result = await session.exec(statement)
    agent_stack_links = result.all()
    for agent_stack_link in agent_stack_links:
        await session.delete(agent_stack_link)

    await session.delete(stack)
    await session.commit()
    return {"message": "Stack deleted successfully"}