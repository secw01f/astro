import logging
import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlmodel import select
from sqlalchemy.orm import noload, selectinload
from typing import Annotated
from haystack.dataclasses import ChatMessage, ChatRole

from src.db.db import async_session, session_dep
from src.db.models import LLM, Agent, Stack, StackPublic, Message, Tool, ToolSet, AgentStackLink, Credential
from lib.auth.auth import verify_token

from lib.agent import SupervisorAgent, SupportingAgent, StreamingCallback
from lib.message import event_stream, fanout, storage_consumer, next_position
from lib.stack.models import CreateStack, ExecuteStack, UpdateStack
from lib.agent.enums import AgentType
from lib.agent.prompts import create_prompt
from lib.llm import chat_generator
from lib.credentials import decrypt_token
from lib.tool.resolver import build_agent_toolset_catalog
from src.tool.memory import MemoryToolset
from src.tool.date import DateToolset
from src.tool.math import MathToolset
from src.tool.spec import SpecToolset
from src.tool.message import MessageToolset
from src.tool.file import FileToolset
from lib.file import FileRunRegistry, FileRunSession, save_user_file
from settings import settings

stack_router = APIRouter(prefix="/stack", dependencies=[Depends(verify_token)])
logger = logging.getLogger(__name__)
_STACK_RUN_EXECUTOR = ThreadPoolExecutor(max_workers=settings.STACK_RUN_MAX_CONCURRENCY)
_STACK_RUN_TASKS: set[asyncio.Task] = set()
_STACK_RUN_SEMAPHORE: asyncio.Semaphore | None = None


def _get_stack_run_semaphore() -> asyncio.Semaphore:
    global _STACK_RUN_SEMAPHORE
    if _STACK_RUN_SEMAPHORE is None:
        _STACK_RUN_SEMAPHORE = asyncio.Semaphore(settings.STACK_RUN_MAX_CONCURRENCY)
    return _STACK_RUN_SEMAPHORE


async def _read_upload_with_limit(file: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail="Uploaded file is too large")
        chunks.append(chunk)
    return b"".join(chunks)

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
                selectinload(Agent.toolsets).selectinload(ToolSet.member_tools).selectinload(Tool.toolset),
                selectinload(Agent.tools).selectinload(Tool.toolset),
                selectinload(Agent.stacks).selectinload(Stack.agents).options(
                    selectinload(Agent.llm),
                    selectinload(Agent.toolsets).selectinload(ToolSet.tools),
                selectinload(Agent.toolsets).selectinload(ToolSet.member_tools).selectinload(Tool.toolset),
                selectinload(Agent.tools).selectinload(Tool.toolset),
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
                selectinload(Agent.toolsets).selectinload(ToolSet.member_tools).selectinload(Tool.toolset),
                selectinload(Agent.tools).selectinload(Tool.toolset),
                selectinload(Agent.stacks).selectinload(Stack.agents).options(
                    selectinload(Agent.llm),
                    selectinload(Agent.toolsets).selectinload(ToolSet.tools),
                selectinload(Agent.toolsets).selectinload(ToolSet.member_tools).selectinload(Tool.toolset),
                selectinload(Agent.tools).selectinload(Tool.toolset),
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

    statement = select(Agent).where(Agent.id.in_(all_agent_ids), Agent.user_id == user_id)
    result = await session.exec(statement)
    all_agents = result.all()
    all_by_id = {agent.id: agent for agent in all_agents if agent.id is not None}

    missing_ids = [agent_id for agent_id in all_agent_ids if agent_id not in all_by_id]
    if missing_ids:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "One or more agents do not exist or are not owned by you",
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
                selectinload(Agent.toolsets).selectinload(ToolSet.member_tools).selectinload(Tool.toolset),
                selectinload(Agent.tools).selectinload(Tool.toolset),
                selectinload(Agent.stacks).selectinload(Stack.agents).options(
                    selectinload(Agent.llm),
                    selectinload(Agent.toolsets).selectinload(ToolSet.tools),
                selectinload(Agent.toolsets).selectinload(ToolSet.member_tools).selectinload(Tool.toolset),
                selectinload(Agent.tools).selectinload(Tool.toolset),
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
    
    statement = (
        select(Stack)
        .where(Stack.id == id, Stack.user_id == user_id)
        .options(selectinload(Stack.agents))
    )
    result = await session.exec(statement)
    existing_stack = result.first()
    if not existing_stack:
        raise HTTPException(status_code=404, detail="Stack not found")

    updates = stack.model_dump(exclude_unset=True)
    supervisor_update = updates.pop("supervisor", None)
    supporting_update = updates.pop("supporting", None)
    for key, value in updates.items():
        setattr(existing_stack, key, value)

    if supervisor_update is not None or supporting_update is not None:
        current_supervisors = [
            agent for agent in existing_stack.agents if agent.agent_type == AgentType.SUPERVISOR
        ]
        current_supporting = [
            agent for agent in existing_stack.agents if agent.agent_type == AgentType.SUPPORTING
        ]
        supervisor_id = supervisor_update
        if supervisor_id is None:
            if not current_supervisors or current_supervisors[0].id is None:
                raise HTTPException(status_code=400, detail="Stack has no supervisor agent")
            supervisor_id = current_supervisors[0].id
        supporting_ids = (
            list(dict.fromkeys(supporting_update))
            if supporting_update is not None
            else [agent.id for agent in current_supporting if agent.id is not None]
        )
        requested_ids = list(dict.fromkeys([supervisor_id, *supporting_ids]))
        agent_stmt = select(Agent).where(Agent.id.in_(requested_ids), Agent.user_id == user_id)
        all_agents = (await session.exec(agent_stmt)).all()
        all_by_id = {agent.id: agent for agent in all_agents if agent.id is not None}
        missing_ids = [agent_id for agent_id in requested_ids if agent_id not in all_by_id]
        if missing_ids:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "One or more agents do not exist or are not owned by you",
                    "agent_ids": missing_ids,
                },
            )
        supervisor_agent = all_by_id[supervisor_id]
        if supervisor_agent.agent_type != AgentType.SUPERVISOR:
            raise HTTPException(status_code=400, detail="Supervisor agent must have type 'supervisor'")
        supporting_agents = [all_by_id[agent_id] for agent_id in supporting_ids]
        wrong_supporting = [agent.id for agent in supporting_agents if agent.agent_type != AgentType.SUPPORTING]
        if wrong_supporting:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Supporting agents must have type 'supporting'",
                    "agent_ids": wrong_supporting,
                },
            )
        existing_stack.agents = [supervisor_agent, *supporting_agents]

    await session.commit()
    statement = (
        select(Stack)
        .options(
            selectinload(Stack.agents).options(
                selectinload(Agent.llm),
                selectinload(Agent.toolsets).selectinload(ToolSet.tools),
                selectinload(Agent.toolsets).selectinload(ToolSet.member_tools).selectinload(Tool.toolset),
                selectinload(Agent.tools).selectinload(Tool.toolset),
                selectinload(Agent.stacks).selectinload(Stack.agents).options(
                    selectinload(Agent.llm),
                    selectinload(Agent.toolsets).selectinload(ToolSet.tools),
                selectinload(Agent.toolsets).selectinload(ToolSet.member_tools).selectinload(Tool.toolset),
                selectinload(Agent.tools).selectinload(Tool.toolset),
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
            .selectinload(ToolSet.tools),
            selectinload(Stack.agents)
            .selectinload(Agent.toolsets)
            .selectinload(ToolSet.member_tools)
            .selectinload(Tool.toolset),
            selectinload(Stack.agents)
            .selectinload(Agent.tools)
            .selectinload(Tool.toolset),
        )
        .where(Stack.id == id, Stack.user_id == user_id)
    )
    _stack_result = await session.exec(_stack_statement)
    _stack = _stack_result.first()

    if not _stack:
        raise HTTPException(status_code=404, detail="Stack not found")

    foreign_agents = [a.id for a in _stack.agents if a.user_id != user_id]
    if foreign_agents:
        raise HTTPException(
            status_code=403,
            detail={
                "message": "Stack contains agents not owned by you",
                "agent_ids": foreign_agents,
            },
        )

    _supervisors = [agent for agent in _stack.agents if agent.agent_type == AgentType.SUPERVISOR]
    if len(_supervisors) == 0:
        raise HTTPException(status_code=400, detail="Stack has no supervisor agent")
    _stack_supervisor = _supervisors[0]

    if _stack_supervisor.llm_id is None:
        raise HTTPException(status_code=400, detail="Supervisor agent is missing an LLM")
    _supervisor_llm = await session.get(LLM, _stack_supervisor.llm_id)
    if _supervisor_llm is None:
        raise HTTPException(status_code=404, detail="Supervisor LLM not found")
    if _supervisor_llm.user_id != user_id:
        raise HTTPException(status_code=403, detail="Supervisor LLM is not owned by you")

    _credential = await session.get(Credential, _supervisor_llm.credential_id)
    if _credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    if _credential.user_id != user_id:
        raise HTTPException(status_code=403, detail="Supervisor LLM credential is not owned by you")
    _token = decrypt_token(_credential.token)

    supervisor_llm = chat_generator(_supervisor_llm.provider, _supervisor_llm.model, _token, _supervisor_llm.key_id, _supervisor_llm.region, _supervisor_llm.max_tokens, user_id=user_id)
    
    run_id = str(uuid.uuid4())

    main_queue = asyncio.Queue()
    client_queue = asyncio.Queue(maxsize=100)
    storage_queue = asyncio.Queue()

    _app_loop = asyncio.get_running_loop()

    file_session = FileRunSession(
        run_id=run_id,
        stack_id=id,
        user_id=user_id,
        queue=main_queue,
        loop=_app_loop,
        agent_name=_stack_supervisor.name,
    )
    _callback = StreamingCallback(
        _stack_supervisor.name,
        main_queue,
        run_id,
        loop=_app_loop,
    )

    support_streams: list[StreamingCallback] = []
    supervisor = SupervisorAgent(
        chat_generator=supervisor_llm,
        system_prompt=create_prompt(_stack_supervisor.system_prompt, AgentType.SUPERVISOR),
        streaming_callback=_callback
    )

    supervisor.add_tool(MemoryToolset(user_id, app_loop=_app_loop))
    supervisor.add_tool(DateToolset())
    supervisor.add_tool(MathToolset())
    supervisor.add_tool(SpecToolset(user_id))
    supervisor.add_tool(MessageToolset(id, user_id, app_loop=_app_loop))
    supervisor.add_tool(
        FileToolset(user_id, file_session=file_session, app_loop=_app_loop)
    )

    _stack_agents = [agent for agent in _stack.agents if agent.agent_type == AgentType.SUPPORTING]

    for agent in _stack_agents:
        if agent.llm_id is None:
            raise HTTPException(status_code=400, detail=f"Supporting agent {agent.id} is missing an LLM")
        _llm = await session.get(LLM, agent.llm_id)
        if _llm is None:
            raise HTTPException(status_code=404, detail=f"LLM {agent.llm_id} for supporting agent {agent.id} not found")
        if _llm.user_id != user_id:
            raise HTTPException(
                status_code=403,
                detail=f"LLM {_llm.id} for supporting agent {agent.id} is not owned by you",
            )

        _credential = await session.get(Credential, _llm.credential_id)
        if _credential is None:
            raise HTTPException(status_code=404, detail=f"Credential {_llm.credential_id} for LLM {agent.llm_id} not found")
        if _credential.user_id != user_id:
            raise HTTPException(
                status_code=403,
                detail=f"Credential for LLM {agent.llm_id} is not owned by you",
            )
        _token = decrypt_token(_credential.token)

        _agent_llm = chat_generator(_llm.provider, _llm.model, _token, _llm.key_id, _llm.region, _llm.max_tokens, user_id=user_id)

        _agent_tools = [
            MemoryToolset(user_id, app_loop=_app_loop),
            DateToolset(),
            MathToolset(),
            SpecToolset(user_id),
            FileToolset(user_id, file_session=file_session, app_loop=_app_loop),
        ]

        _agent_tools.extend(
            await build_agent_toolset_catalog(session, agent, user_id)
        )

        _support_stream = StreamingCallback(
            agent.name,
            main_queue,
            run_id,
            loop=_app_loop,
        )
        support_streams.append(_support_stream)
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

    async def storage_worker():
        async with async_session() as storage_session:
            await storage_consumer(storage_queue, storage_session, id, user_id)

    client_closed = asyncio.Event()

    async def fanout_worker():
        await fanout(
            main_queue,
            client_queue,
            storage_queue,
            verbose=execute.verbose,
            supervisor_agent_name=_stack_supervisor.name,
            client_closed=client_closed,
        )

    async def runner():
        fanout_task = asyncio.create_task(fanout_worker())
        storage_task = asyncio.create_task(storage_worker())
        try:
            messages_for_run = [ChatMessage.from_user(execute.message)]
            result = await _app_loop.run_in_executor(
                _STACK_RUN_EXECUTOR,
                partial(supervisor.run, messages=messages_for_run),
            )

            await asyncio.sleep(0)

            final_text = None
            for msg in reversed((result or {}).get("messages") or []):
                if msg.is_from(ChatRole.ASSISTANT) and msg.text:
                    final_text = msg.text
                    break
            _callback.emit_final_assistant_text(final_text)
        except Exception as e:
            logger.exception("Stack run failed", exc_info=e)
            _callback.emit_final_assistant_text("Stack execution failed.")
        finally:
            FileRunRegistry.unregister(run_id)
            for callback in support_streams:
                if callback.started:
                    callback.end()
            _callback.end()
            await asyncio.sleep(0)
            await main_queue.put(None)
            try:
                await fanout_task
                await storage_task
            finally:
                _get_stack_run_semaphore().release()

    semaphore = _get_stack_run_semaphore()
    if semaphore.locked():
        raise HTTPException(status_code=429, detail="Too many stack runs are already active")
    await semaphore.acquire()
    try:
        FileRunRegistry.register(file_session)
        task = asyncio.create_task(runner())
    except Exception:
        FileRunRegistry.unregister(run_id)
        semaphore.release()
        raise
    _STACK_RUN_TASKS.add(task)
    task.add_done_callback(_STACK_RUN_TASKS.discard)

    return StreamingResponse(
        event_stream(client_queue, client_closed),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@stack_router.post("/{id}/run/{run_id}/file")
async def submit_run_file(
    request: Request,
    id: int,
    run_id: str,
    request_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, str]:
    claims = getattr(request.state, "claims", None)
    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]
    file_session = FileRunRegistry.get(run_id)
    if file_session is None:
        raise HTTPException(status_code=404, detail="Stack run not found or already finished")
    if file_session.stack_id != id or file_session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Stack run not found")

    content = await _read_upload_with_limit(file, settings.MAX_UPLOAD_BYTES)
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    row = await asyncio.to_thread(
        save_user_file,
        user_id,
        file.filename or "upload",
        content,
        content_type=file.content_type,
    )
    resolved = file_session.resolve(
        request_id,
        {
            "file_id": row["id"],
            "filename": row["filename"],
            "content_type": row["content_type"],
            "size": row["size"],
        },
    )
    if not resolved:
        raise HTTPException(
            status_code=404,
            detail="File request not found or already fulfilled",
        )

    return {
        "request_id": request_id,
        "file_id": row["id"],
        "filename": row["filename"],
    }


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
