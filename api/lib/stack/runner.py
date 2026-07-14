import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from haystack.dataclasses import ChatMessage, ChatRole
from sqlalchemy.orm import selectinload
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from lib.agent import SupervisorAgent, SupportingAgent, StreamingCallback
from lib.agent.enums import AgentType
from lib.agent.prompts import create_prompt
from lib.credentials import decrypt_token
from lib.file import FileRunRegistry, FileRunSession
from lib.llm import chat_generator
from lib.message import fanout, next_position, storage_consumer
from lib.tool.resolver import build_agent_toolset_catalog
from src.db.db import async_session
from src.db.models import (
    Agent,
    Credential,
    LLM,
    Message,
    Stack,
    StackSchedule,
    StackScheduleRun,
    Tool,
    ToolSet,
)
from lib.stack.models import StackScheduleRunStatus
from lib.stack.schedule import advance_schedule_after_dispatch, complete_schedule_time

logger = logging.getLogger(__name__)

_STACK_RUN_LOAD_OPTIONS = (
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


class StackRunError(Exception):
    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@dataclass
class PreparedStackRun:
    stack: Stack
    supervisor_agent: Agent
    supervisor: SupervisorAgent
    callback: StreamingCallback
    file_session: FileRunSession
    run_id: str
    app_loop: asyncio.AbstractEventLoop


async def load_stack_for_run(
    session: AsyncSession,
    stack_id: int,
    user_id: int,
) -> Stack:
    statement = (
        select(Stack)
        .options(*_STACK_RUN_LOAD_OPTIONS)
        .where(Stack.id == stack_id, Stack.user_id == user_id)
    )
    result = await session.exec(statement)
    stack = result.first()

    if not stack:
        raise StackRunError(404, "Stack not found")

    foreign_agents = [a.id for a in stack.agents if a.user_id != user_id]
    if foreign_agents:
        raise StackRunError(
            403,
            {
                "message": "Stack contains agents not owned by you",
                "agent_ids": foreign_agents,
            },
        )

    supervisors = [agent for agent in stack.agents if agent.agent_type == AgentType.SUPERVISOR]
    if not supervisors:
        raise StackRunError(400, "Stack has no supervisor agent")

    return stack


async def prepare_stack_run(
    session: AsyncSession,
    stack_id: int,
    user_id: int,
    *,
    app_loop: asyncio.AbstractEventLoop | None = None,
    run_id: str | None = None,
) -> PreparedStackRun:
    from src.tool.date import DateToolset
    from src.tool.file import FileToolset
    from src.tool.math import MathToolset
    from src.tool.memory import MemoryToolset
    from src.tool.message import MessageToolset
    from src.tool.spec import SpecToolset

    stack = await load_stack_for_run(session, stack_id, user_id)
    stack_supervisor = next(
        agent for agent in stack.agents if agent.agent_type == AgentType.SUPERVISOR
    )

    if stack_supervisor.llm_id is None:
        raise StackRunError(400, "Supervisor agent is missing an LLM")
    supervisor_llm_row = await session.get(LLM, stack_supervisor.llm_id)
    if supervisor_llm_row is None:
        raise StackRunError(404, "Supervisor LLM not found")
    if supervisor_llm_row.user_id != user_id:
        raise StackRunError(403, "Supervisor LLM is not owned by you")

    credential = await session.get(Credential, supervisor_llm_row.credential_id)
    if credential is None:
        raise StackRunError(404, "Credential not found")
    if credential.user_id != user_id:
        raise StackRunError(403, "Supervisor LLM credential is not owned by you")
    token = decrypt_token(credential.token)

    supervisor_llm = chat_generator(
        supervisor_llm_row.provider,
        supervisor_llm_row.model,
        token,
        supervisor_llm_row.key_id,
        supervisor_llm_row.region,
        supervisor_llm_row.max_tokens,
    )

    loop = app_loop or asyncio.get_running_loop()
    resolved_run_id = run_id or str(uuid.uuid4())
    main_queue: asyncio.Queue = asyncio.Queue()

    file_session = FileRunSession(
        run_id=resolved_run_id,
        stack_id=stack_id,
        user_id=user_id,
        queue=main_queue,
        loop=loop,
        agent_name=stack_supervisor.name,
    )
    FileRunRegistry.register(file_session)

    callback = StreamingCallback(
        stack_supervisor.name,
        main_queue,
        resolved_run_id,
        loop=loop,
    )

    supervisor = SupervisorAgent(
        chat_generator=supervisor_llm,
        system_prompt=create_prompt(stack_supervisor.system_prompt, AgentType.SUPERVISOR),
        streaming_callback=callback,
    )

    supervisor.add_tool(MemoryToolset(user_id, app_loop=loop))
    supervisor.add_tool(DateToolset())
    supervisor.add_tool(MathToolset())
    supervisor.add_tool(SpecToolset())
    supervisor.add_tool(MessageToolset(stack_id, user_id, app_loop=loop))
    supervisor.add_tool(FileToolset(user_id, file_session=file_session, app_loop=loop))

    for agent in [a for a in stack.agents if a.agent_type == AgentType.SUPPORTING]:
        if agent.llm_id is None:
            raise StackRunError(400, f"Supporting agent {agent.id} is missing an LLM")
        llm_row = await session.get(LLM, agent.llm_id)
        if llm_row is None:
            raise StackRunError(
                404,
                f"LLM {agent.llm_id} for supporting agent {agent.id} not found",
            )
        if llm_row.user_id != user_id:
            raise StackRunError(
                403,
                f"LLM {llm_row.id} for supporting agent {agent.id} is not owned by you",
            )

        agent_credential = await session.get(Credential, llm_row.credential_id)
        if agent_credential is None:
            raise StackRunError(
                404,
                f"Credential {llm_row.credential_id} for LLM {agent.llm_id} not found",
            )
        if agent_credential.user_id != user_id:
            raise StackRunError(
                403,
                f"Credential for LLM {agent.llm_id} is not owned by you",
            )
        agent_token = decrypt_token(agent_credential.token)

        agent_llm = chat_generator(
            llm_row.provider,
            llm_row.model,
            agent_token,
            llm_row.key_id,
            llm_row.region,
            llm_row.max_tokens,
        )

        agent_tools = [
            MemoryToolset(user_id, app_loop=loop),
            DateToolset(),
            MathToolset(),
            SpecToolset(),
            FileToolset(user_id, file_session=file_session, app_loop=loop),
        ]
        agent_tools.extend(await build_agent_toolset_catalog(session, agent, user_id))

        support_stream = StreamingCallback(
            agent.name,
            main_queue,
            resolved_run_id,
            loop=loop,
        )
        supporting = SupportingAgent(
            chat_generator=agent_llm,
            name=agent.name,
            description=agent.description,
            system_prompt=create_prompt(agent.system_prompt, AgentType.SUPPORTING),
            user_prompt="""{% message role="user" %}{{prompt}}{% endmessage %}""",
            required_variables=["prompt"],
            tools=agent_tools,
            streaming_callback=support_stream,
        )
        supervisor.register_supporting_agent(supporting)

    supervisor.warm_up()

    return PreparedStackRun(
        stack=stack,
        supervisor_agent=stack_supervisor,
        supervisor=supervisor,
        callback=callback,
        file_session=file_session,
        run_id=resolved_run_id,
        app_loop=loop,
    )


async def persist_user_message(
    session: AsyncSession,
    stack_id: int,
    user_id: int,
    message: str,
) -> int:
    """Persist the user turn and return its message id."""
    position = await next_position(session, stack_id, user_id)
    row = Message(
        role="user",
        content=message,
        position=position,
        stack_id=stack_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    if row.id is None:
        raise StackRunError(500, "Failed to persist user message")
    return row.id


async def _resolve_last_message_id(
    session: AsyncSession,
    stack_id: int,
    user_message_id: int,
) -> int:
    stmt = (
        select(Message.id)
        .where(
            Message.stack_id == stack_id,
            Message.id >= user_message_id,
        )
        .order_by(Message.id.desc())
        .limit(1)
    )
    last_id = (await session.exec(stmt)).first()
    return last_id if last_id is not None else user_message_id


async def _ensure_run_messages_persisted(
    stack_id: int,
    user_id: int,
    user_message_id: int,
    final_text: str | None,
) -> int:
    """Guarantee the assistant reply is stored and return the run's last message id.

    The streaming storage worker normally persists the assistant turn. This is a
    safety net for the background path: if nothing was written after the user
    message, persist ``final_text`` so the run always has a retrievable transcript.
    """
    async with async_session() as session:
        count_stmt = (
            select(func.count())
            .select_from(Message)
            .where(
                Message.stack_id == stack_id,
                Message.id > user_message_id,
            )
        )
        follow_up_count = (await session.exec(count_stmt)).one()

        if follow_up_count == 0 and final_text:
            position = await next_position(session, stack_id, user_id)
            row = Message(
                role="assistant",
                content=final_text,
                stack_id=stack_id,
                position=position,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.id if row.id is not None else user_message_id

        return await _resolve_last_message_id(session, stack_id, user_message_id)


@dataclass
class StackRunOutcome:
    run_id: str
    final_text: str | None
    error: str | None = None
    user_message_id: int | None = None
    last_message_id: int | None = None


async def execute_stack_run(
    prepared: PreparedStackRun,
    stack_id: int,
    message: str,
    *,
    verbose: bool = False,
    client_queue: asyncio.Queue | None = None,
    user_message_id: int | None = None,
    user_id: int | None = None,
) -> StackRunOutcome:
    main_queue = prepared.callback.queue
    storage_queue: asyncio.Queue = asyncio.Queue()
    discard_queue: asyncio.Queue = asyncio.Queue()
    stream_queue = client_queue or discard_queue

    async def storage_worker():
        async with async_session() as storage_session:
            await storage_consumer(
                storage_queue,
                storage_session,
                stack_id,
            )

    async def fanout_worker():
        await fanout(
            main_queue,
            stream_queue,
            storage_queue,
            verbose=verbose,
            supervisor_agent_name=prepared.supervisor_agent.name,
        )

    fanout_task = asyncio.create_task(fanout_worker())
    storage_task = asyncio.create_task(storage_worker())
    final_text: str | None = None
    error: str | None = None

    try:
        messages_for_run = [ChatMessage.from_user(message)]
        result = await asyncio.to_thread(prepared.supervisor.run, messages=messages_for_run)

        await asyncio.sleep(0)

        for msg in reversed((result or {}).get("messages") or []):
            if msg.is_from(ChatRole.ASSISTANT) and msg.text:
                final_text = msg.text
                break
        prepared.callback.emit_final_assistant_text(final_text)
    except Exception as exc:
        logger.exception("Stack run failed", exc_info=exc)
        error = str(exc)
        final_text = f"Stack execution failed: {error}"
        prepared.callback.emit_final_assistant_text(final_text)
    finally:
        FileRunRegistry.unregister(prepared.run_id)
        prepared.callback.end()
        await asyncio.sleep(0)
        await main_queue.put(None)
        await fanout_task
        await storage_task
        if user_message_id is not None and user_id is not None:
            last_message_id = await _ensure_run_messages_persisted(
                stack_id,
                user_id,
                user_message_id,
                final_text,
            )
        else:
            last_message_id = None

    return StackRunOutcome(
        run_id=prepared.run_id,
        final_text=final_text,
        error=error,
        user_message_id=user_message_id,
        last_message_id=last_message_id,
    )


async def run_stack_background(
    stack_id: int,
    user_id: int,
    message: str,
    *,
    verbose: bool = False,
    run_id: str | None = None,
) -> StackRunOutcome:
    async with async_session() as session:
        user_message_id = await persist_user_message(session, stack_id, user_id, message)

    try:
        loop = asyncio.get_running_loop()
        async with async_session() as session:
            prepared = await prepare_stack_run(
                session,
                stack_id,
                user_id,
                app_loop=loop,
                run_id=run_id,
            )
    except StackRunError as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return StackRunOutcome(
            run_id=run_id or "",
            final_text=None,
            error=detail,
            user_message_id=user_message_id,
            last_message_id=user_message_id,
        )
    except Exception as exc:
        error = str(exc) or type(exc).__name__
        return StackRunOutcome(
            run_id=run_id or "",
            final_text=None,
            error=error,
            user_message_id=user_message_id,
            last_message_id=user_message_id,
        )

    outcome = await execute_stack_run(
        prepared,
        stack_id,
        message,
        verbose=verbose,
        user_message_id=user_message_id,
        user_id=user_id,
    )
    outcome.user_message_id = user_message_id
    return outcome


async def execute_interactive_stack(
    stack_id: int,
    user_id: int,
    message: str,
    run_id: str,
    user_message_id: int,
    verbose: bool = False,
) -> StackRunOutcome:
    """Run an interactive stack inside a worker, streaming over Redis.

    The user message is already persisted by the API before this is enqueued;
    ``user_message_id`` lets ``execute_stack_run`` finalize the transcript.
    Run events are published to a Redis stream (via ``RedisEventPublisher``) and
    file-upload results arrive over a Redis control channel that ``consume_control``
    applies to the run's file session.
    """
    from lib.stack.streambus import RedisEventPublisher, consume_control

    publisher = RedisEventPublisher(run_id)
    control_task: asyncio.Task | None = None
    try:
        async with async_session() as session:
            prepared = await prepare_stack_run(
                session,
                stack_id,
                user_id,
                run_id=run_id,
            )
        control_task = asyncio.create_task(
            consume_control(run_id, prepared.file_session)
        )
        return await execute_stack_run(
            prepared,
            stack_id,
            message,
            verbose=verbose,
            client_queue=publisher,
            user_message_id=user_message_id,
            user_id=user_id,
        )
    except StackRunError as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        await publisher.emit_error(detail)
        return StackRunOutcome(
            run_id=run_id,
            final_text=None,
            error=detail,
            user_message_id=user_message_id,
            last_message_id=user_message_id,
        )
    except Exception as exc:
        logger.exception("Interactive stack run failed", exc_info=exc)
        detail = str(exc) or type(exc).__name__
        await publisher.emit_error(detail)
        return StackRunOutcome(
            run_id=run_id,
            final_text=None,
            error=detail,
            user_message_id=user_message_id,
            last_message_id=user_message_id,
        )
    finally:
        if control_task is not None:
            control_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await control_task
        await publisher.put(None)
        await publisher.aclose()


async def process_due_stack_schedules() -> list[tuple[int, int | None]]:
    now = datetime.utcnow()
    dispatches: list[tuple[int, int | None]] = []

    async with async_session() as session:
        statement = (
            select(StackSchedule)
            .where(
                StackSchedule.enabled == True,
                StackSchedule.next_run_at <= now,
            )
            .order_by(StackSchedule.next_run_at)
        )
        result = await session.exec(statement)
        due_schedules = result.all()

        for schedule in due_schedules:
            if schedule.id is None:
                continue
            schedule_time_id = await advance_schedule_after_dispatch(
                session,
                schedule,
                now=now,
            )
            dispatches.append((schedule.id, schedule_time_id))

        await session.commit()

    return dispatches


async def execute_scheduled_stack(
    schedule_id: int,
    schedule_time_id: int | None = None,
) -> None:
    now = datetime.utcnow()

    async with async_session() as session:
        schedule = await session.get(StackSchedule, schedule_id)
        if schedule is None:
            return
        if not schedule.enabled and schedule_time_id is None:
            return

        run_id = str(uuid.uuid4())
        run_row = StackScheduleRun(
            schedule_id=schedule.id,
            schedule_time_id=schedule_time_id,
            stack_id=schedule.stack_id,
            user_id=schedule.user_id,
            run_id=run_id,
            status=StackScheduleRunStatus.RUNNING,
            started_at=now,
        )
        session.add(run_row)
        schedule.last_run_at = now
        await session.commit()
        await session.refresh(run_row)

        run_row_id = run_row.id
        stack_id = schedule.stack_id
        user_id = schedule.user_id
        message = schedule.message
        verbose = schedule.verbose

    try:
        outcome = await run_stack_background(
            stack_id,
            user_id,
            message,
            verbose=verbose,
            run_id=run_id,
        )
    except StackRunError as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        outcome = StackRunOutcome(run_id=run_id, final_text=None, error=detail)
    except Exception as exc:
        logger.exception("Scheduled stack run failed", exc_info=exc)
        outcome = StackRunOutcome(
            run_id=run_id,
            final_text=None,
            error=str(exc) or type(exc).__name__,
        )

    failed = bool(outcome.error) or (
        outcome.final_text is None
        and outcome.user_message_id is not None
        and outcome.last_message_id == outcome.user_message_id
    )

    async with async_session() as session:
        run_row = await session.get(StackScheduleRun, run_row_id)
        if run_row is None:
            return

        run_row.completed_at = datetime.utcnow()
        if failed:
            run_row.status = StackScheduleRunStatus.FAILED
            run_row.error = outcome.error or "Scheduled stack run produced no assistant response"
            run_row.result = outcome.final_text
        else:
            run_row.status = StackScheduleRunStatus.COMPLETED
            run_row.result = outcome.final_text
        run_row.message_start_id = outcome.user_message_id
        run_row.message_end_id = outcome.last_message_id
        await complete_schedule_time(
            session,
            schedule_time_id,
            succeeded=not failed,
        )
        session.add(run_row)
        await session.commit()
