import typer

from cli.src import users, routers

cli = typer.Typer()

cli.add_typer(users.app, name="users")
cli.add_typer(routers.app, name="router")

if __name__ == "__main__":
    cli()