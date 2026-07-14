from datetime import datetime, timedelta

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from lib.stack.models import StackScheduleTimeStatus, StackScheduleType
from lib.stack.recurrence import next_recurring_run_at
from src.db.models import StackSchedule, StackScheduleTime


def normalize_run_times(run_times: list[datetime], *, now: datetime) -> list[datetime]:
    unique = sorted({time.replace(tzinfo=None) for time in run_times})
    if not unique:
        raise ValueError("At least one run time is required")
    if any(time <= now for time in unique):
        raise ValueError("All run times must be in the future")
    return unique


async def create_schedule_times(
    session: AsyncSession,
    schedule_id: int,
    run_times: list[datetime],
) -> datetime:
    for run_at in run_times:
        session.add(
            StackScheduleTime(
                schedule_id=schedule_id,
                run_at=run_at,
                status=StackScheduleTimeStatus.PENDING,
            )
        )
    return run_times[0]


async def replace_pending_schedule_times(
    session: AsyncSession,
    schedule: StackSchedule,
    run_times: list[datetime],
    *,
    now: datetime,
) -> datetime:
    statement = select(StackScheduleTime).where(
        StackScheduleTime.schedule_id == schedule.id,
        StackScheduleTime.status == StackScheduleTimeStatus.PENDING,
    )
    result = await session.exec(statement)
    for time_slot in result.all():
        await session.delete(time_slot)

    normalized = normalize_run_times(run_times, now=now)
    return await create_schedule_times(session, schedule.id, normalized)


async def next_pending_run_at(
    session: AsyncSession,
    schedule_id: int,
) -> datetime | None:
    statement = (
        select(StackScheduleTime)
        .where(
            StackScheduleTime.schedule_id == schedule_id,
            StackScheduleTime.status == StackScheduleTimeStatus.PENDING,
        )
        .order_by(StackScheduleTime.run_at)
    )
    result = await session.exec(statement)
    next_slot = result.first()
    return next_slot.run_at if next_slot is not None else None


async def advance_schedule_after_dispatch(
    session: AsyncSession,
    schedule: StackSchedule,
    *,
    now: datetime,
) -> int | None:
    if schedule.schedule_type == StackScheduleType.INTERVAL:
        if schedule.interval_seconds is None:
            raise ValueError("Interval schedule is missing interval_seconds")
        schedule.next_run_at = now + timedelta(seconds=schedule.interval_seconds)
        session.add(schedule)
        return None

    if schedule.schedule_type == StackScheduleType.RECURRING:
        if schedule.recurrence is None or schedule.recurrence_day is None:
            raise ValueError("Recurring schedule is missing recurrence configuration")
        schedule.next_run_at = next_recurring_run_at(
            schedule.recurrence,
            schedule.recurrence_day,
            schedule.recurrence_hour,
            schedule.recurrence_minute,
            after=now,
        )
        session.add(schedule)
        return None

    statement = (
        select(StackScheduleTime)
        .where(
            StackScheduleTime.schedule_id == schedule.id,
            StackScheduleTime.status == StackScheduleTimeStatus.PENDING,
            StackScheduleTime.run_at <= now,
        )
        .order_by(StackScheduleTime.run_at)
    )
    result = await session.exec(statement)
    due_slot = result.first()
    if due_slot is None:
        return None

    next_statement = (
        select(StackScheduleTime)
        .where(
            StackScheduleTime.schedule_id == schedule.id,
            StackScheduleTime.status == StackScheduleTimeStatus.PENDING,
            StackScheduleTime.run_at > due_slot.run_at,
        )
        .order_by(StackScheduleTime.run_at)
    )
    next_result = await session.exec(next_statement)
    next_slot = next_result.first()
    if next_slot is None:
        schedule.enabled = False
        schedule.next_run_at = due_slot.run_at
    else:
        schedule.next_run_at = next_slot.run_at
    session.add(schedule)

    return due_slot.id


async def complete_schedule_time(
    session: AsyncSession,
    schedule_time_id: int | None,
    *,
    succeeded: bool,
) -> None:
    if schedule_time_id is None:
        return

    time_slot = await session.get(StackScheduleTime, schedule_time_id)
    if time_slot is None:
        return

    time_slot.status = (
        StackScheduleTimeStatus.COMPLETED
        if succeeded
        else StackScheduleTimeStatus.FAILED
    )
    session.add(time_slot)
