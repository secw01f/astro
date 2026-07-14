import re
from datetime import datetime

import click
import json

from lib.color import cyan, red, white

WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_DURATION_PATTERN = re.compile(r"^(\d+)([smhdw])$", re.IGNORECASE)
_DURATION_UNITS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}


def parse_duration(value: str) -> int:
    match = _DURATION_PATTERN.match(value.strip())
    if not match:
        raise ValueError(
            "Duration must look like 30s, 15m, 2h, 1d, or 1w"
        )
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if amount <= 0:
        raise ValueError("Duration must be greater than zero")
    return amount * _DURATION_UNITS[unit]


def parse_run_times(values: tuple[str, ...]) -> list[str]:
    if not values:
        raise ValueError("At least one --run-at value is required")
    normalized: list[str] = []
    for value in values:
        text = value.strip()
        if " " in text and "T" not in text:
            text = text.replace(" ", "T", 1)
        try:
            datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(
                f"Invalid datetime '{value}'. Use ISO format like 2026-07-20T14:00:00"
            ) from exc
        normalized.append(text)
    return normalized


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "(none)"
    if seconds % 604800 == 0:
        weeks = seconds // 604800
        return f"{weeks} week{'s' if weeks != 1 else ''}"
    if seconds % 86400 == 0:
        days = seconds // 86400
        return f"{days} day{'s' if days != 1 else ''}"
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''}"
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{seconds} seconds"


def format_recurrence_day(recurrence: str | None, day: int | None) -> str:
    if recurrence is None or day is None:
        return "(none)"
    if recurrence == "weekly":
        if 0 <= day <= 6:
            return WEEKDAY_NAMES[day]
        return str(day)
    return f"day {day}"


def format_schedule_times(run_times: list[dict]) -> str:
    if not run_times:
        return "(none)"
    parts: list[str] = []
    for slot in run_times:
        run_at = slot.get("run_at", "?")
        status = slot.get("status", "?")
        parts.append(f"{run_at} [{status}]")
    return "; ".join(parts)


def format_schedule(schedule: dict) -> str:
    schedule_type = schedule.get("schedule_type", "?")
    lines = [
        f"{cyan('ID:', 'bold')} {schedule.get('id', '?')}",
        f"{cyan('Stack ID:', 'bold')} {schedule.get('stack_id', '?')}",
        f"{cyan('Name:', 'bold')} {schedule.get('name', '?')}",
        f"{cyan('Type:', 'bold')} {schedule_type}",
        f"{cyan('Message:', 'bold')} {schedule.get('message', '')}",
        f"{cyan('Enabled:', 'bold')} {schedule.get('enabled', False)}",
        f"{cyan('Verbose:', 'bold')} {schedule.get('verbose', False)}",
        f"{cyan('Next run:', 'bold')} {schedule.get('next_run_at', '?')}",
        f"{cyan('Last run:', 'bold')} {schedule.get('last_run_at') or '(never)'}",
        f"{cyan('Created:', 'bold')} {schedule.get('created', '?')}",
    ]
    if schedule_type == "interval":
        lines.insert(4, f"{cyan('Every:', 'bold')} {format_duration(schedule.get('interval_seconds'))}")
    elif schedule_type == "fixed":
        lines.insert(4, f"{cyan('Run times:', 'bold')} {format_schedule_times(schedule.get('run_times') or [])}")
    elif schedule_type == "recurring":
        recurrence = schedule.get("recurrence")
        day = schedule.get("recurrence_day")
        hour = schedule.get("recurrence_hour", 0)
        minute = schedule.get("recurrence_minute", 0)
        lines.insert(
            4,
            f"{cyan('Recurrence:', 'bold')} {recurrence or '?'} on "
            f"{format_recurrence_day(recurrence, day)} at {hour:02d}:{minute:02d} UTC",
        )
    return "\n".join(lines)


def format_schedule_run(run: dict) -> str:
    lines = [
        f"{cyan('ID:', 'bold')} {run.get('id', '?')}",
        f"{cyan('Schedule ID:', 'bold')} {run.get('schedule_id', '?')}",
        f"{cyan('Stack ID:', 'bold')} {run.get('stack_id', '?')}",
        f"{cyan('Run ID:', 'bold')} {run.get('run_id', '?')}",
        f"{cyan('Status:', 'bold')} {run.get('status', '?')}",
        f"{cyan('Started:', 'bold')} {run.get('started_at', '?')}",
        f"{cyan('Completed:', 'bold')} {run.get('completed_at') or '(pending)'}",
    ]
    if run.get("schedule_time_id") is not None:
        lines.append(f"{cyan('Time slot ID:', 'bold')} {run['schedule_time_id']}")
    if run.get("error"):
        lines.append(f"{cyan('Error:', 'bold')} {run['error']}")
    if run.get("result"):
        lines.append(f"{cyan('Result:', 'bold')} {run['result']}")
    return "\n".join(lines)


def format_run_messages(messages: list[dict]) -> str:
    if not messages:
        return "(no messages recorded for this run)"
    lines: list[str] = []
    for message in messages:
        role = message.get("role", "?")
        content = message.get("content", "")
        if role == "tool":
            try:
                payload = json.loads(content)
                content = (
                    f"[tool:{payload.get('tool_name', '?')}] "
                    f"{payload.get('result_preview') or payload.get('error') or content}"
                )
            except json.JSONDecodeError:
                pass
        lines.append(f"{cyan(f'{role.capitalize()}:', 'bold')} {content}")
    return "\n\n".join(lines)


def format_stacks(stacks: list[dict]) -> str:
    if not stacks:
        return "(none)"
    parts: list[str] = []
    for stack in stacks:
        stack_id = stack.get("id", "?")
        name = stack.get("name", "?")
        description = stack.get("description", "")
        if description:
            parts.append(f"{stack_id}: {name} ({description})")
        else:
            parts.append(f"{stack_id}: {name}")
    return ", ".join(parts)

def get_agents_by_type(ctx: click.Context) -> tuple[list[dict], list[dict]] | tuple[None, None]:
    client = ctx.obj["client"]
    response = client.get("/agent/agents")
    if response.status_code != 200:
        click.echo(red("Failed to list agents", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return None, None

    agents = response.json().get("agents", [])
    supervisors = [agent for agent in agents if agent.get("agent_type") == "supervisor"]
    supporting_agents = [agent for agent in agents if agent.get("agent_type") == "supporting"]
    return supervisors, supporting_agents
