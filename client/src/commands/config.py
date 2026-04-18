import click
import pathlib
import json

from lib.color import green, red

@click.group(help="Configure the ASTRO client")
def config():
    pass

@config.command()
@click.argument("url", type=click.STRING)
def url(url: str):
    if not url:
        click.echo(f"{red("API URL is required", "bold")}")
        return
    _config_file = pathlib.Path.home() / ".astro" / "config.json"
    with open(_config_file, "r") as f:
        _config = json.load(f)
    _config["url"] = url
    with open(_config_file, "w") as f:
        json.dump(_config, f, indent=4)
    click.echo(f"{green("API URL set to", "bold")} {url}")
    return