import click
import json
import httpx

from lib.color import cyan, magenta, red, white

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

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue

                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue

                typ = data.get("type")
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
                elif typ == "end":
                    break
                elif typ == "error":
                    click.secho("")
                    click.secho(red(data.get("content"), "bold"))
                    break

            click.secho("/n")
    except httpx.ConnectError:
        click.secho(red("Failed to connect to the API", "bold"))
        return
    except httpx.ReadTimeout:
        click.secho(red("Read timed out waiting for the API (response too slow).", "bold"))
        return
