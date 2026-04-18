import click
import json
import httpx

from lib.color import cyan, red, white

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

async def stream(ctx: click.Context, id: int, message: str, name: str) -> None:
    client = ctx.obj["async_client"]

    try:
        stream_timeout = httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0)
        async with client.stream(
            "POST",
            f"/stack/{id}/exec",
            json={"message": message},
            timeout=stream_timeout,
        ) as response:
            if response.status_code != 200:
                await response.aread()
                click.secho(red("Failed to execute stack", "bold"))
                click.echo(white(f"Error: {response.text}", "normal"))
                return

            click.secho(cyan(f"{name}: ", "bold"))

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue

                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue

                if data.get("type") == "token":
                    click.secho(data.get("content"), nl=False)
                elif data.get("type") == "end":
                    break
                elif data.get("type") == "error":
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
