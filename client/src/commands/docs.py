import click
import pathlib
import json

from lib.color import green

@click.command(help="Open the docs in your browser")
def docs():
    with (pathlib.Path.home() / ".astro" / "config.json").open("r") as f:
        config = json.load(f)
    click.launch(config["url"] + "/docs")
    click.echo(green("Docs opened in your browser", "bold"))