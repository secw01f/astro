import click
import httpx
import os

from lib.color import red, white
from lib.banner import banner
from lib.config import ensure_config_file, resolve_runtime

from src.commands.config import config
from src.commands.init import init
from src.commands.auth import auth
from src.commands.agent import agents
from src.commands.tool import tools
from src.commands.llm import llms
from src.commands.docs import docs
from src.commands.stack import stacks

_SETUP_COMMANDS = frozenset({"init", "config"})

class BannerGroup(click.Group):
    def get_help(self, ctx: click.Context) -> str:
        return f"{banner()}\n\n{super().get_help(ctx)}"

@click.group(cls=BannerGroup)
@click.pass_context
def astro(ctx: click.Context):
    subcommand = ctx.invoked_subcommand
    if subcommand in _SETUP_COMMANDS:
        ctx.ensure_object(dict)
        return

    url, token = resolve_runtime()
    if not url:
        click.echo(f"{red('API URL is not set', 'bold')}")
        click.echo(f"{white('Run `astro init` for interactive setup, or `astro config url <url>`.', 'normal')}")
        raise SystemExit(1)

    if not os.getenv("ASTRO_API_URL") and not os.getenv("ASTRO_API_TOKEN"):
        ensure_config_file()

    ctx.ensure_object(dict)
    ctx.obj["url"] = url
    ctx.obj["client"] = httpx.Client(base_url=url)

    if token is not None:
        ctx.obj["client"].headers.update({"X-API-KEY": token})

astro.add_command(init)
astro.add_command(config)
astro.add_command(docs)
astro.add_command(auth)
astro.add_command(agents)
astro.add_command(tools)
astro.add_command(llms)
astro.add_command(stacks)

if __name__ == "__main__":
    astro()