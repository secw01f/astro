import logging
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlmodel import select
from sqlalchemy.orm import noload, selectinload
from typing import Annotated

from src.db.db import session_dep
from src.db.models import (
    Agent,
    Stack,
    StackPublic,
    Message,
    MessagePublic,
    Tool,
    ToolSet,
    AgentStackLink,
    StackSchedule,
    StackScheduleRun,
    StackScheduleTime,
)
from lib.auth.auth import verify_token

from lib.stack.models import (
    CreateStack,
    ExecuteStack,
    UpdateStack,
    CreateStackSchedule,
    UpdateStackSchedule,
    StackSchedulePublic,
    StackScheduleRunPublic,
    StackScheduleTimePublic,
    StackScheduleType,
)
from lib.stack.recurrence import next_recurring_run_at
from lib.stack.schedule import (
    create_schedule_times,
    normalize_run_times,
    replace_pending_schedule_times,
)
from lib.stack.runner import (
    StackRunError,
    persist_user_message,
)
from lib.stack.streambus import (
    get_run_meta,
    publish_file_result,
    set_run_meta,
    stream_run_events,
)
from lib.agent.enums import AgentType
from lib.file import save_user_file
from src.celery.tasks import run_interactive_stack_task

INTERACTIVE_QUEUE = "interactive"

stack_router = APIRouter(prefix="/stack", dependencies=[Depends(verify_token)])
logger = logging.getLogger(__name__)

_SCHEDULE_LOAD_OPTIONS = (selectinload(StackSchedule.times),)


def _schedule_time_to_public(time_slot: StackScheduleTime) -> StackScheduleTimePublic:
    return StackScheduleTimePublic(
        id=time_slot.id,
        run_at=time_slot.run_at,
        status=time_slot.status,
    )


def _schedule_to_public(schedule: StackSchedule) -> StackSchedulePublic:
    times = sorted(schedule.times or [], key=lambda slot: slot.run_at)
    return StackSchedulePublic(
        id=schedule.id,
        stack_id=schedule.stack_id,
        name=schedule.name,
        message=schedule.message,
        schedule_type=schedule.schedule_type,
        interval_seconds=schedule.interval_seconds,
        run_times=[_schedule_time_to_public(time_slot) for time_slot in times],
        recurrence=schedule.recurrence,
        recurrence_day=schedule.recurrence_day,
        recurrence_hour=schedule.recurrence_hour,
        recurrence_minute=schedule.recurrence_minute,
        enabled=schedule.enabled,
        verbose=schedule.verbose,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        created=schedule.created,
    )


def _schedule_run_to_public(run: StackScheduleRun) -> StackScheduleRunPublic:
    return StackScheduleRunPublic(
        id=run.id,
        schedule_id=run.schedule_id,
        stack_id=run.stack_id,
        run_id=run.run_id,
        schedule_time_id=run.schedule_time_id,
        status=run.status,
        result=run.result,
        error=run.error,
        started_at=run.started_at,
        completed_at=run.completed_at,
        message_start_id=run.message_start_id,
        message_end_id=run.message_end_id,
    )


async def _get_owned_schedule(
    session: session_dep,
    schedule_id: int,
    user_id: int,
) -> StackSchedule:
    statement = (
        select(StackSchedule)
        .where(StackSchedule.id == schedule_id, StackSchedule.user_id == user_id)
        .options(*_SCHEDULE_LOAD_OPTIONS)
    )
    result = await session.exec(statement)
    schedule = result.first()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


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


@stack_router.post("/schedule/create")
async def create_stack_schedule(
    request: Request,
    body: CreateStackSchedule,
    session: session_dep,
) -> dict[str, StackSchedulePublic]:
    claims = getattr(request.state, "claims", None)
    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]
    stack = await session.get(Stack, body.stack_id)
    if stack is None or stack.user_id != user_id:
        raise HTTPException(status_code=404, detail="Stack not found")

    now = datetime.utcnow()
    try:
        if body.schedule_type == StackScheduleType.FIXED:
            run_times = normalize_run_times(body.run_times or [], now=now)
            next_run_at = run_times[0]
            interval_seconds = None
            recurrence = None
            recurrence_day = None
            recurrence_hour = 0
            recurrence_minute = 0
        elif body.schedule_type == StackScheduleType.RECURRING:
            run_times = []
            interval_seconds = None
            recurrence = body.recurrence
            recurrence_day = body.recurrence_day
            recurrence_hour = body.recurrence_hour
            recurrence_minute = body.recurrence_minute
            next_run_at = next_recurring_run_at(
                recurrence,
                recurrence_day,
                recurrence_hour,
                recurrence_minute,
                after=now,
            )
        else:
            run_times = []
            interval_seconds = body.interval_seconds
            recurrence = None
            recurrence_day = None
            recurrence_hour = 0
            recurrence_minute = 0
            next_run_at = now
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    schedule = StackSchedule(
        name=body.name,
        stack_id=body.stack_id,
        user_id=user_id,
        message=body.message,
        schedule_type=body.schedule_type,
        interval_seconds=interval_seconds,
        recurrence=recurrence,
        recurrence_day=recurrence_day,
        recurrence_hour=recurrence_hour,
        recurrence_minute=recurrence_minute,
        enabled=body.enabled,
        verbose=body.verbose,
        next_run_at=next_run_at,
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)

    if body.schedule_type == StackScheduleType.FIXED:
        await create_schedule_times(session, schedule.id, run_times)
        await session.commit()

    schedule = await _get_owned_schedule(session, schedule.id, user_id)
    return {"schedule": _schedule_to_public(schedule)}


@stack_router.get("/schedules")
async def list_stack_schedules(
    request: Request,
    session: session_dep,
) -> dict[str, list[StackSchedulePublic]]:
    claims = getattr(request.state, "claims", None)
    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]
    statement = (
        select(StackSchedule)
        .where(StackSchedule.user_id == user_id)
        .options(*_SCHEDULE_LOAD_OPTIONS)
        .order_by(StackSchedule.created.desc())
    )
    result = await session.exec(statement)
    schedules = result.all()
    return {"schedules": [_schedule_to_public(schedule) for schedule in schedules]}


@stack_router.get("/schedule/run/{run_id}")
async def get_stack_schedule_run(
    request: Request,
    run_id: str,
    session: session_dep,
) -> dict[str, StackScheduleRunPublic]:
    claims = getattr(request.state, "claims", None)
    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]
    statement = select(StackScheduleRun).where(
        StackScheduleRun.run_id == run_id,
        StackScheduleRun.user_id == user_id,
    )
    result = await session.exec(statement)
    run = result.first()
    if run is None:
        raise HTTPException(status_code=404, detail="Scheduled run not found")

    return {"run": _schedule_run_to_public(run)}


@stack_router.get("/schedule/run/{run_id}/messages")
async def get_stack_schedule_run_messages(
    request: Request,
    run_id: str,
    session: session_dep,
) -> dict[str, list[MessagePublic]]:
    claims = getattr(request.state, "claims", None)
    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]
    statement = select(StackScheduleRun).where(
        StackScheduleRun.run_id == run_id,
        StackScheduleRun.user_id == user_id,
    )
    result = await session.exec(statement)
    run = result.first()
    if run is None:
        raise HTTPException(status_code=404, detail="Scheduled run not found")

    if run.message_start_id is None:
        return {"messages": []}

    message_statement = (
        select(Message)
        .where(
            Message.stack_id == run.stack_id,
            Message.id >= run.message_start_id,
        )
        .order_by(Message.id)
    )
    if run.message_end_id is not None:
        message_statement = message_statement.where(
            Message.id <= run.message_end_id
        )

    message_result = await session.exec(message_statement)
    messages = message_result.all()
    return {"messages": [MessagePublic.model_validate(message) for message in messages]}


@stack_router.get("/schedule/{schedule_id}")
async def get_stack_schedule(
    request: Request,
    schedule_id: int,
    session: session_dep,
) -> dict[str, StackSchedulePublic]:
    claims = getattr(request.state, "claims", None)
    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]
    schedule = await _get_owned_schedule(session, schedule_id, user_id)
    return {"schedule": _schedule_to_public(schedule)}


@stack_router.patch("/schedule/{schedule_id}")
async def update_stack_schedule(
    request: Request,
    schedule_id: int,
    body: Annotated[UpdateStackSchedule, Body(...)],
    session: session_dep,
) -> dict[str, StackSchedulePublic]:
    claims = getattr(request.state, "claims", None)
    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]
    schedule = await _get_owned_schedule(session, schedule_id, user_id)

    updates = body.model_dump(exclude_unset=True)
    run_times = updates.pop("run_times", None)
    new_schedule_type = updates.get("schedule_type", schedule.schedule_type)
    recurrence_fields = {
        "recurrence",
        "recurrence_day",
        "recurrence_hour",
        "recurrence_minute",
    }
    recurrence_changed = bool(recurrence_fields & updates.keys())

    if new_schedule_type == StackScheduleType.INTERVAL:
        if run_times is not None:
            raise HTTPException(
                status_code=400,
                detail="run_times cannot be set for interval schedules",
            )
        if recurrence_changed:
            raise HTTPException(
                status_code=400,
                detail="recurrence fields cannot be set for interval schedules",
            )
        if "interval_seconds" in updates:
            schedule.next_run_at = datetime.utcnow() + timedelta(
                seconds=updates["interval_seconds"]
            )
    elif new_schedule_type == StackScheduleType.FIXED:
        if "interval_seconds" in updates:
            raise HTTPException(
                status_code=400,
                detail="interval_seconds cannot be set for fixed schedules",
            )
        if recurrence_changed:
            raise HTTPException(
                status_code=400,
                detail="recurrence fields cannot be set for fixed schedules",
            )
        if run_times is not None:
            try:
                schedule.next_run_at = await replace_pending_schedule_times(
                    session,
                    schedule,
                    run_times,
                    now=datetime.utcnow(),
                )
                schedule.enabled = True
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif new_schedule_type == StackScheduleType.RECURRING:
        if "interval_seconds" in updates:
            raise HTTPException(
                status_code=400,
                detail="interval_seconds cannot be set for recurring schedules",
            )
        if run_times is not None:
            raise HTTPException(
                status_code=400,
                detail="run_times cannot be set for recurring schedules",
            )

    for key, value in updates.items():
        setattr(schedule, key, value)

    if schedule.schedule_type == StackScheduleType.RECURRING:
        if schedule.recurrence is None or schedule.recurrence_day is None:
            raise HTTPException(
                status_code=400,
                detail="recurrence and recurrence_day are required for recurring schedules",
            )
        if recurrence_changed or "schedule_type" in updates:
            try:
                schedule.next_run_at = next_recurring_run_at(
                    schedule.recurrence,
                    schedule.recurrence_day,
                    schedule.recurrence_hour,
                    schedule.recurrence_minute,
                    after=datetime.utcnow(),
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    session.add(schedule)
    await session.commit()
    schedule = await _get_owned_schedule(session, schedule_id, user_id)
    return {"schedule": _schedule_to_public(schedule)}


@stack_router.delete("/schedule/{schedule_id}")
async def delete_stack_schedule(
    request: Request,
    schedule_id: int,
    session: session_dep,
) -> dict[str, str]:
    claims = getattr(request.state, "claims", None)
    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]
    schedule = await session.get(StackSchedule, schedule_id)
    if schedule is None or schedule.user_id != user_id:
        raise HTTPException(status_code=404, detail="Schedule not found")

    statement = select(StackScheduleRun).where(StackScheduleRun.schedule_id == schedule_id)
    result = await session.exec(statement)
    for run in result.all():
        await session.delete(run)

    time_statement = select(StackScheduleTime).where(
        StackScheduleTime.schedule_id == schedule_id
    )
    time_result = await session.exec(time_statement)
    for time_slot in time_result.all():
        await session.delete(time_slot)

    await session.delete(schedule)
    await session.commit()
    return {"message": "Schedule deleted successfully"}


@stack_router.get("/schedule/{schedule_id}/runs")
async def list_stack_schedule_runs(
    request: Request,
    schedule_id: int,
    session: session_dep,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, list[StackScheduleRunPublic]]:
    claims = getattr(request.state, "claims", None)
    if not claims or "id" not in claims:
        raise HTTPException(status_code=401, detail="Missing JWT claims on request")

    user_id = claims["id"]
    schedule = await session.get(StackSchedule, schedule_id)
    if schedule is None or schedule.user_id != user_id:
        raise HTTPException(status_code=404, detail="Schedule not found")

    safe_limit = max(1, min(limit, 100))
    safe_offset = max(0, offset)
    statement = (
        select(StackScheduleRun)
        .where(StackScheduleRun.schedule_id == schedule_id)
        .order_by(StackScheduleRun.started_at.desc())
        .offset(safe_offset)
        .limit(safe_limit)
    )
    result = await session.exec(statement)
    runs = result.all()
    return {"runs": [_schedule_run_to_public(run) for run in runs]}


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

    try:
        user_message_id = await persist_user_message(session, id, user_id, execute.message)
    except StackRunError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    run_id = str(uuid.uuid4())
    await set_run_meta(run_id, id, user_id)
    run_interactive_stack_task.apply_async(
        args=[id, user_id, execute.message, run_id, user_message_id, execute.verbose],
        queue=INTERACTIVE_QUEUE,
    )

    return StreamingResponse(
        stream_run_events(run_id, request.is_disconnected),
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
    meta = await get_run_meta(run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Stack run not found or already finished")
    if meta["stack_id"] != id or meta["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Stack run not found")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    row = save_user_file(
        user_id,
        file.filename or "upload",
        content,
        content_type=file.content_type,
    )
    await publish_file_result(
        run_id,
        request_id,
        {
            "file_id": row["id"],
            "filename": row["filename"],
            "content_type": row["content_type"],
            "size": row["size"],
        },
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

    statement = select(StackScheduleRun).where(StackScheduleRun.stack_id == id)
    result = await session.exec(statement)
    for schedule_run in result.all():
        await session.delete(schedule_run)

    statement = select(StackSchedule).where(StackSchedule.stack_id == id)
    result = await session.exec(statement)
    schedules = result.all()
    for schedule in schedules:
        time_statement = select(StackScheduleTime).where(
            StackScheduleTime.schedule_id == schedule.id
        )
        time_result = await session.exec(time_statement)
        for time_slot in time_result.all():
            await session.delete(time_slot)
        await session.delete(schedule)

    statement = select(AgentStackLink).where(AgentStackLink.stack_id == id)
    result = await session.exec(statement)
    agent_stack_links = result.all()
    for agent_stack_link in agent_stack_links:
        await session.delete(agent_stack_link)

    await session.delete(stack)
    await session.commit()
    return {"message": "Stack deleted successfully"}
