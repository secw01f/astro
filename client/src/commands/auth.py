import click

from lib.auth import persist_token
from lib.color import cyan, green

@click.group(help="Authenticate to the ASTRO API")
def auth():
    pass

@auth.command()
@click.pass_context
@click.option("--username", required=True, help="The username to login with")
def login(ctx: click.Context, username: str):
    password = click.prompt("Password", hide_input=True)
    client = ctx.obj["client"]

    r = client.post("/auth/token", json={
        "username": username,
        "password": password
    })

    if r.status_code != 200:
        click.echo(f"Failed to login: {r.text}")
        return

    persist_token(r.json()["token"])

    click.echo(f"{green("Logged in successfully", "bold")}")

@auth.command()
@click.pass_context
def me(ctx: click.Context):
    client = ctx.obj["client"]
    response = client.get("/auth/user/me")
    if response.status_code != 200:
        click.echo(f"Failed to get user: {response.text}")
        return
    user = response.json()["user"]
    click.echo(f"{cyan("ID:", "bold")} {user['id']}\n{cyan("Username:", "bold")} {user['username']}\n{cyan("Email:", "bold")} {user['email']}")