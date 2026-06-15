import click
import httpx

from lib.auth import persist_token
from lib.color import cyan, green, red, white

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

@auth.command()
@click.pass_context
@click.option("--id", "user_id", required=False, type=int, help="User ID to update (admin use)")
@click.option("--username", required=False, help="New username")
@click.option("--email", required=False, help="New email")
@click.option("--password", required=False, is_flag=True, help="Update password (individual user only)", default=False)
@click.option("--role", required=False, type=click.Choice(["admin", "user"]), help="Set role (admin use)")
@click.option("--enabled/--disabled", "enabled", default=None, help="Set user enabled state (admin use)")
def update(ctx: click.Context, user_id: int | None, username: str | None, email: str | None, password: bool, role: str | None, enabled: bool | None):
    client = ctx.obj["client"]

    payload: dict = {}
    if username is not None:
        payload["username"] = username
    if email is not None:
        payload["email"] = email
    if role is not None:
        payload["role"] = role
    if enabled is not None:
        payload["enabled"] = enabled
    if password:
        new_password = click.prompt("New password", hide_input=True)
        payload["new_password"] = new_password
    if user_id is None and any(key in payload for key in ("username", "email", "new_password")):
        payload["current_password"] = click.prompt("Current password", hide_input=True)

    if not payload:
        click.echo(red("No update fields provided", "bold"))
        click.echo(white("Use one or more options like --email, --password, --role, etc.", "normal"))
        return

    endpoint = f"/auth/user/{user_id}" if user_id is not None else "/auth/user/me"
    response = client.patch(endpoint, json=payload)

    if response.status_code != 200:
        click.echo(red("Failed to update user", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return
    click.echo(green("User updated successfully", "bold"))

@auth.command()
@click.pass_context
@click.option("--id", "user_id", required=False, type=int, help="User ID to delete (admin use)")
def delete(ctx: click.Context, user_id: int | None):
    client = ctx.obj["client"]
    endpoint = f"/auth/user/{user_id}" if user_id is not None else "/auth/user/me"
    response = client.delete(endpoint)
    if response.status_code != 200:
        click.echo(red("Failed to delete user", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return
    click.echo(green("User deleted successfully", "bold"))

@auth.command()
@click.pass_context
def create(ctx: click.Context):
    client = ctx.obj["client"]
    username = click.prompt("Username")
    email = click.prompt("Email")
    role = click.prompt("Role", type=click.Choice(["admin", "user"]))
    response = client.post("/auth/user/create", json={
        "username": username,
        "email": email,
        "role": role,
    })
    if response.status_code != 200:
        click.echo(red("Failed to create user", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return
    data = response.json()
    click.echo(green("User created successfully", "bold"))
    temporary_password = data.get("temporary_password")
    if temporary_password:
        click.echo(white(f"Temporary password: {temporary_password}", "normal"))

@auth.command()
@click.pass_context
@click.option("--token", required=True, help="The token to reset the password")
def reset_password(ctx: click.Context, token: str):
    password = click.prompt("New password", hide_input=True)
    # No JWT: use a one-off request without the stored X-API-KEY header
    base = str(ctx.obj["url"]).rstrip("/")
    response = httpx.post(
        f"{base}/auth/user/reset-password",
        json={"token": token, "new_password": password},
        timeout=30.0,
    )
    if response.status_code != 200:
        click.echo(red("Failed to reset password", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return
    click.echo(green("Password reset successfully", "bold"))

@auth.command()
@click.pass_context
def users(ctx: click.Context):
    client = ctx.obj["client"]
    response = client.get("/auth/users")
    if response.status_code != 200:
        click.echo(red("Failed to get users", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return
    users = response.json()["users"]
    for user in users:
        click.echo(f"{cyan("ID:", "bold")} {user['id']}\n{cyan("Username:", "bold")} {user['username']}\n{cyan("Email:", "bold")} {user['email']}\n{cyan("Role:", "bold")} {user['role']}\n{cyan("Enabled:", "bold")} {user['enabled']}")

@auth.command()
@click.pass_context
@click.option("--id", "user_id", required=True, type=int, help="User ID to get")
def user(ctx: click.Context, user_id: int):
    client = ctx.obj["client"]
    response = client.get(f"/auth/user/{user_id}")
    if response.status_code != 200:
        click.echo(red("Failed to get user", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return
    user = response.json()["user"]
    click.echo(f"{cyan("ID:", "bold")} {user['id']}\n{cyan("Username:", "bold")} {user['username']}\n{cyan("Email:", "bold")} {user['email']}\n{cyan("Role:", "bold")} {user['role']}\n{cyan("Enabled:", "bold")} {user['enabled']}")
