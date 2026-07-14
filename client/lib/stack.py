import asyncio
import os
import re
from datetime import datetime

import click
import json
import httpx

from lib.color import cyan, green, magenta, red, white, yellow

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

def _needs_sentence_space(last_char: str | None, chunk: str) -> bool:
    if not last_char or not chunk:
        return False
    if chunk[0].isspace() or chunk[0] in ".,!?;:)]}\"'":
        return False
    return last_char in ".!?"

async def upload_run_file(
    ctx: click.Context,
    stack_id: int,
    run_id: str,
    request_id: str,
    path: str,
) -> bool:
    client = ctx.obj["async_client"]
    filename = os.path.basename(path)

    try:
        with open(path, "rb") as handle:
            response = await client.post(
                f"/stack/{stack_id}/run/{run_id}/file",
                data={"request_id": request_id},
                files={"file": (filename, handle)},
            )
    except OSError as exc:
        click.secho(red(f"Could not read file: {exc}", "bold"))
        return False

    if response.status_code != 200:
        click.secho(red("Failed to upload file", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return False

    payload = response.json()
    click.secho(
        green(
            f"Uploaded {payload.get('filename', filename)} "
            f"(file_id={payload.get('file_id')})",
            "bold",
        )
    )
    return True

async def _prompt_and_upload_file(
    ctx: click.Context,
    stack_id: int,
    run_id: str,
    request_id: str,
    description: str,
) -> bool:
    click.secho("")
    click.secho(yellow("File requested by agent", "bold"))
    click.echo(white(description or "Please provide a file.", "normal"))
    click.echo(white(f"Request ID: {request_id}", "normal"))
    path = await asyncio.to_thread(click.prompt, "Path to file", type=str)
    return await upload_run_file(ctx, stack_id, run_id, request_id, path)

async def chat_loop(
    ctx: click.Context,
    stack_id: int,
    name: str,
    *,
    verbose: bool = False,
    username: str,
    chat_commands: dict[str, str],
) -> None:
    """Run the interactive stack chat on one event loop (safe for httpx.AsyncClient)."""
    sync_client = ctx.obj["client"]

    while True:
        try:
            user_input = await asyncio.to_thread(
                click.prompt,
                magenta(f"{username}@astro", "bold"),
            )
        except (click.Abort, EOFError, KeyboardInterrupt):
            break

        message = user_input.strip()
        if not message:
            continue

        cmd = message.lower()
        if cmd in chat_commands:
            if cmd in ("/exit", "/quit", "/q"):
                break
            if cmd == "/clear":
                click.clear()
            elif cmd == "/history":
                response = sync_client.post(
                    "/message/history",
                    json={"stack_id": stack_id, "limit": 10, "offset": 0},
                )
                if response.status_code != 200:
                    click.echo(red("Failed to get message history", "bold"))
                    click.echo(white(f"Error: {response.text}", "normal"))
                    continue
                for history_message in response.json()["messages"]:
                    if history_message["role"] == "assistant":
                        click.echo(
                            f"{cyan(f'{history_message['role'].capitalize()}:', 'bold')} "
                            f"{white(history_message['content'], 'normal')}"
                        )
                    elif history_message["role"] == "user":
                        click.echo(
                            f"{magenta(f'{username}@astro:', 'bold')} "
                            f"{white(history_message['content'], 'normal')}"
                        )
                    click.echo("")
            elif cmd in ("/help", "/h"):
                for command, description in chat_commands.items():
                    click.echo(f"{green(f'{command}:', 'bold')} {white(description, 'normal')}")
            elif cmd in ("/info", "/i"):
                response = sync_client.get(f"/stack/{stack_id}")
                if response.status_code != 200:
                    click.echo(red("Failed to get stack info", "bold"))
                    click.echo(white(f"Error: {response.text}", "normal"))
                    continue
                stack = response.json()["stack"]
                click.echo(f"{cyan('Name:', 'bold')} {stack['name']}")
                click.echo(f"{cyan('Description:', 'bold')} {stack['description']}")
                click.echo(f"{cyan('Created:', 'bold')} {stack['created']}")
            elif cmd in ("/f", "/file"):
                run_id = await asyncio.to_thread(click.prompt, "Run ID", type=str)
                request_id = await asyncio.to_thread(click.prompt, "Request ID", type=str)
                path = await asyncio.to_thread(click.prompt, "Path to file", type=str)
                await upload_run_file(ctx, stack_id, run_id, request_id, path)
            continue

        click.secho("")
        await stream(ctx, stack_id, message, name, verbose=verbose)


async def stream(ctx: click.Context, id: int, message: str, name: str, *, verbose: bool = False) -> None:
    client = ctx.obj["async_client"]

    try:
        stream_timeout = httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0)
        payload = {"message": message, "verbose": verbose}
        async with client.stream(
            "POST",
            f"/stack/{id}/exec",
            json=payload,
            timeout=stream_timeout,
        ) as response:
            if response.status_code != 200:
                await response.aread()
                click.secho(red("Failed to execute stack", "bold"))
                click.echo(white(f"Error: {response.text}", "normal"))
                return

            if verbose:
                click.secho(white("Verbose stream (each agent is labeled when their tokens begin).", "normal"))
                click.secho("")
            else:
                click.secho(cyan(f"{name}: ", "bold"))

            last_token_agent: str | None = None
            last_rendered_char: str | None = None
            run_id: str | None = None

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue

                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue

                typ = data.get("type")
                if run_id is None and data.get("run_id"):
                    run_id = data["run_id"]

                if typ == "token":
                    ag = data.get("agent")
                    if verbose and isinstance(ag, str) and ag != last_token_agent:
                        click.secho("")
                        click.secho(magenta(f"{ag}: ", "bold"), nl=False)
                        last_token_agent = ag
                    content = data.get("content") or ""
                    if _needs_sentence_space(last_rendered_char, content):
                        content = " " + content
                    click.secho(content, nl=False)
                    if content:
                        last_rendered_char = content[-1]
                elif typ == "file_request":
                    request_id = data.get("request_id")
                    event_run_id = data.get("run_id") or run_id
                    if not request_id or not event_run_id:
                        click.secho(red("Invalid file_request event (missing ids)", "bold"))
                        continue
                    await _prompt_and_upload_file(
                        ctx,
                        id,
                        event_run_id,
                        request_id,
                        data.get("description") or "",
                    )
                elif typ == "end":
                    break
                elif typ == "error":
                    click.secho("")
                    click.secho(red(data.get("content"), "bold"))
                    break

            click.secho("\n")
    except httpx.ConnectError:
        click.secho(red("Failed to connect to the API", "bold"))
        return
    except httpx.ReadTimeout:
        click.secho(red("Read timed out waiting for the API (response too slow).", "bold"))
        return
