import click
import httpx
import asyncio
import pathlib
import json
import os

from lib.color import red, white
from lib.banner import banner

from src.commands.config import config
from src.commands.auth import auth
from src.commands.agent import agents
from src.commands.tool import tools
from src.commands.llm import llms
from src.commands.docs import docs
from src.commands.stack import stacks

class BannerGroup(click.Group):
    def get_help(self, ctx: click.Context) -> str:
        return f"{banner()}\n\n{super().get_help(ctx)}"

@click.group(cls=BannerGroup)
@click.pass_context
def astro(ctx: click.Context):
    _home = pathlib.Path.home()
    _config_file = _home / ".astro" / "config.json"

    if _config_file.exists():
        with open(_config_file, "r") as f:
            _config = json.load(f)
            if not _config["url"]:
                click.echo(f"{red("API URL is not set", "bold")}")
                click.echo(f"{white("Please set the API URL in the config file or in the environment variables", "normal")}")
                click.echo(f"{white("Use `astro config url` to set the API URL", "normal")}")
                return
    elif os.getenv("ASTRO_API_TOKEN") is not None and os.getenv("ASTRO_API_URL") is not None:
        _token = os.getenv("ASTRO_API_TOKEN")
        _url = os.getenv("ASTRO_API_URL")
    else:
        _config_file.parent.mkdir(parents=True, exist_ok=True)
        _config_file.touch()
        _config = {
            "token": None,
            "url": "http://localhost:8000"
        }
        with open(_config_file, "w") as f:
            json.dump(_config, f, indent=4)

    ctx.ensure_object(dict)
    ctx.obj["url"] = _config["url"]
    ctx.obj["client"] = httpx.Client(base_url=ctx.obj["url"])
    ctx.obj["async_client"] = httpx.AsyncClient(base_url=ctx.obj["url"])

    if _config["token"] is not None:
        ctx.obj["client"].headers.update({
            "X-API-KEY": _config["token"]
        })
        ctx.obj["async_client"].headers.update({
            "X-API-KEY": _config["token"]
        })

@astro.result_callback()
@click.pass_context
def close_client(ctx: click.Context, *_args, **_kwargs):
    async_client = ctx.obj.get("async_client")
    if async_client is not None:
        asyncio.run(async_client.aclose())

astro.add_command(config)
astro.add_command(docs)
astro.add_command(auth)
astro.add_command(agents)
astro.add_command(tools)
astro.add_command(llms)
astro.add_command(stacks)

if __name__ == "__main__":
    astro()