import click

from lib.color import cyan, green, red, white
from lib.config import ensure_config_file, load_config, mask_token, save_config, set_url


@click.group(help="Configure the ASTRO client")
def config():
    pass


@config.command("show")
def show():
    """Show current CLI configuration."""
    cfg = load_config()
    click.echo(f"{cyan('Config file', 'bold')}: ~/.astro/config.json")
    click.echo(f"{cyan('API URL', 'bold')}: {cfg.get('url') or '(not set)'}")
    click.echo(f"{cyan('API token', 'bold')}: {mask_token(cfg.get('token'))}")
    click.echo("")
    click.echo(white("Environment overrides (when set):", "normal"))
    click.echo(f"  ASTRO_API_URL")
    click.echo(f"  ASTRO_API_TOKEN")


@config.command()
@click.argument("url", type=click.STRING)
def url(url: str):
    """Set the API base URL."""
    if not url.strip():
        click.echo(f"{red('API URL is required', 'bold')}")
        raise SystemExit(1)
    set_url(url.strip())
    click.echo(f"{green('API URL set to', 'bold')} {url.strip().rstrip('/')}")


@config.command("reset")
@click.confirmation_option(prompt="Reset CLI config to defaults?")
def reset():
    """Reset ~/.astro/config.json to defaults (clears saved token)."""
    from lib.config import default_config

    save_config(default_config())
    click.echo(green("Configuration reset.", "bold"))
