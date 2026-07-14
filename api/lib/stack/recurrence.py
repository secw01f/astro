from calendar import monthrange
from datetime import datetime, timedelta

from lib.stack.models import StackScheduleRecurrence


def validate_recurrence_day(
    recurrence: StackScheduleRecurrence,
    recurrence_day: int,
) -> None:
    if recurrence == StackScheduleRecurrence.WEEKLY:
        if not 0 <= recurrence_day <= 6:
            raise ValueError("recurrence_day must be 0-6 for weekly schedules (0=Monday)")
    elif recurrence == StackScheduleRecurrence.MONTHLY:
        if not 1 <= recurrence_day <= 31:
            raise ValueError("recurrence_day must be 1-31 for monthly schedules")


def _month_day(year: int, month: int, target_day: int) -> int:
    return min(target_day, monthrange(year, month)[1])


def next_weekly_run_at(
    weekday: int,
    hour: int,
    minute: int,
    *,
    after: datetime,
) -> datetime:
    run_at = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    days_ahead = (weekday - after.weekday()) % 7
    if days_ahead == 0 and run_at <= after:
        days_ahead = 7
    return run_at + timedelta(days=days_ahead)


def next_monthly_run_at(
    day_of_month: int,
    hour: int,
    minute: int,
    *,
    after: datetime,
) -> datetime:
    year = after.year
    month = after.month
    day = _month_day(year, month, day_of_month)
    run_at = datetime(year, month, day, hour, minute)

    if run_at <= after:
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
        day = _month_day(year, month, day_of_month)
        run_at = datetime(year, month, day, hour, minute)

    return run_at


def next_recurring_run_at(
    recurrence: StackScheduleRecurrence,
    recurrence_day: int,
    recurrence_hour: int,
    recurrence_minute: int,
    *,
    after: datetime,
) -> datetime:
    validate_recurrence_day(recurrence, recurrence_day)
    if recurrence == StackScheduleRecurrence.WEEKLY:
        return next_weekly_run_at(
            recurrence_day,
            recurrence_hour,
            recurrence_minute,
            after=after,
        )
    return next_monthly_run_at(
        recurrence_day,
        recurrence_hour,
        recurrence_minute,
        after=after,
    )
