import asyncio
import os

import click
import json
import httpx

from lib.color import cyan, green, magenta, red, white, yellow

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
