import click

from lib.color import magenta, red, white, green

@click.group(help="List tools and manage toolsets")
def tools():
    pass

@tools.command(name="list", help="List tools and toolsets; ID is a tool id unless --toolsets is set")
@click.pass_context
@click.option("--toolsets", is_flag=True, help="List toolsets", show_default=True)
@click.option("--tools", is_flag=True, help="List tools", show_default=True, default=True)
@click.argument("id", type=click.INT, required=False)
def list_tools_and_toolsets(ctx: click.Context, toolsets: bool, tools: bool, id: int):
    client = ctx.obj["client"]
    if toolsets:
        tools = False
        if id:
            response = client.get(f"/tool/toolsets/{id}")
            if response.status_code != 200:
                click.echo(f"Failed to get toolset: {response.text}")
                return
            toolset = response.json()["toolset"]
            click.echo(f"{magenta("ID:", "bold")} {toolset['id']}\n{magenta("Name:", "bold")} {toolset['name']}\n{magenta("Description:", "bold")} {toolset['description']}\n{magenta("Type:", "bold")} {toolset['type']}\n{magenta("Created:", "bold")} {toolset['created']}")
            return

        response = client.get("/tool/toolsets")
        if response.status_code != 200:
            click.echo(f"Failed to list toolsets: {response.text}")
            return
        toolsets = response.json()["toolsets"]
        for toolset in toolsets:
            click.echo(f"{magenta("ID:", "bold")} {toolset['id']}\n{magenta("Name:", "bold")} {toolset['name']}\n{magenta("Description:", "bold")} {toolset['description']}\n{magenta("Type:", "bold")} {toolset['type']}\n{magenta("Created:", "bold")} {toolset['created']}")
            click.echo("\n")
        return
    if tools:
        if id:
            response = client.get(f"/tool/{id}")
            if response.status_code != 200:
                click.echo(f"Failed to get tool: {response.text}")
                return
            tool = response.json()["tool"]
            click.echo(f"{magenta("ID:", "bold")} {tool['id']}\n{magenta("Name:", "bold")} {tool['name']}\n{magenta("Description:", "bold")} {tool['description']}\n{magenta("Type:", "bold")} {tool['type']}\n{magenta("Created:", "bold")} {tool['created']}")
            return

        response = client.get("/tool/tools")
        if response.status_code != 200:
            click.echo(f"Failed to list tools: {response.text}")
            return
        tools = response.json()["tools"]
        for tool in tools:
            click.echo(f"{magenta("ID:", "bold")} {tool['id']}\n{magenta("Name:", "bold")} {tool['name']}\n{magenta("Description:", "bold")} {tool['description']}\n{magenta("Type:", "bold")} {tool['type']}\n{magenta("Created:", "bold")} {tool['created']}")
            click.echo("\n")
        return

@tools.command(name="create", help="Create a new Toolset")
@click.pass_context
@click.option("--name", type=click.STRING, required=True, help="Name of the tool")
@click.option("--description", type=click.STRING, required=True, help="Description of the tool")
@click.option("--type", type=click.Choice(["http", "mcp"]), required=True, help="Type of the tool")
@click.option("--url", type=click.STRING, required=False, help="URL of the tool")
@click.option("--auth-required", is_flag=True, default=False, help="Require authentication for this toolset")
@click.option("--auth-type", type=click.Choice(["bearer", "header"]), required=False, help="Authentication type when auth is required")
@click.option("--token", type=click.STRING, required=False, help="Raw token used to create a credential when auth is required")
@click.option("--header", type=click.STRING, required=False, help="Custom header name (required when --auth-type header)")
def create(
    ctx: click.Context,
    name: str,
    description: str,
    type: str,
    url: str,
    auth_required: bool,
    auth_type: str | None,
    token: str | None,
    header: str | None,
):
    client = ctx.obj["client"]

    if auth_required and not auth_type:
        click.echo(red("Failed to create toolset", "bold"))
        click.echo(white("Error: --auth-type is required when --auth-required is set", "normal"))
        return
    if auth_required and not token:
        click.echo(red("Failed to create toolset", "bold"))
        click.echo(white("Error: --token is required when --auth-required is set", "normal"))
        return
    if auth_required and auth_type == "header" and not header:
        click.echo(red("Failed to create toolset", "bold"))
        click.echo(white("Error: --header is required when --auth-type header is set", "normal"))
        return

    payload = {
        "name": name,
        "description": description,
        "url": url,
        "auth_required": auth_required,
        "auth_type": auth_type,
        "token": token,
        "header": header,
    }

    if type == "mcp":
        create_response = client.post("/tool/create/toolset/mcp", json=payload)
        if create_response.status_code != 200:
            click.echo(red("Failed to create MCP toolset", "bold"))
            click.echo(white(f"Error: {create_response.text}", "normal"))
            return

        toolset = create_response.json()["toolset"]

        click.echo(f"{magenta("ID:", "bold")} {toolset['id']}\n{magenta("Name:", "bold")} {toolset['name']}\n{magenta("Description:", "bold")} {toolset['description']}\n{magenta("Type:", "bold")} {toolset['type']}\n{magenta("Created:", "bold")} {toolset['created']}")
        return

    else:
        create_response = client.post("/tool/create/toolset/http", json=payload)

        if create_response.status_code != 200:
            click.echo(red("Failed to create HTTP toolset", "bold"))
            click.echo(white(f"Error: {create_response.text}", "normal"))
            return

        toolset = create_response.json()["toolset"]

        click.echo(f"{magenta("ID:", "bold")} {toolset['id']}\n{magenta("Name:", "bold")} {toolset['name']}\n{magenta("Description:", "bold")} {toolset['description']}\n{magenta("Type:", "bold")} {toolset['type']}\n{magenta("Created:", "bold")} {toolset['created']}")
        return

@tools.command(name="delete", help="Delete a toolset")
@click.pass_context
@click.argument("id", type=click.INT)
def delete_toolset(ctx: click.Context, id: int):
    client = ctx.obj["client"]
    delete_response = client.delete(f"/tool/toolset/{id}")
    if delete_response.status_code != 200:
        click.echo(red("Failed to delete toolset", "bold"))
        click.echo(white(f"Error: {delete_response.text}", "normal"))
        return

    click.echo(green("Toolset deleted successfully", "bold"))