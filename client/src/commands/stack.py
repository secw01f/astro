import click
import asyncio

from lib.color import cyan, green, magenta, red, white
from lib.wizard import select_many_ids, select_one

from lib.stack import get_agents_by_type, stream

def _return_stack(stack: dict) -> None:
    click.echo(
        f"{cyan('ID:', 'bold')} {stack['id']}\n"
        f"{cyan('Name:', 'bold')} {stack['name']}\n"
        f"{cyan('Description:', 'bold')} {stack['description']}\n"
        f"{cyan('Created:', 'bold')} {stack['created']}"
    )

_chat_commands = {
    "/exit": "Quit the chat",
    "/quit": "Quit the chat",
    "/q": "Quit the chat",
    "/clear": "Clear the terminal screen",
    "/history": "Show the chat history",
    "/help": "Show the help",
    "/h": "Show the help",
    "/info": "Show the Stack info",
    "/i": "Show the Stack info",
    "/f": "Upload a file",
    "/file": "Upload a file",
}

@click.group(help="Manage ASTRO stacks")
def stacks():
    pass

@stacks.command(name="list", help="List all stacks")
@click.pass_context
def list_stacks(ctx: click.Context):
    client = ctx.obj["client"]
    response = client.get("/stack/stacks")
    if response.status_code != 200:
        click.echo(red("Failed to list stacks", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return

    stacks_data = response.json()["stacks"]
    if not stacks_data:
        click.echo(red("No stacks found", "bold"))
        click.echo(white("Use `astro stack create` to create a new stack", "normal"))
        return

    for stack in stacks_data:
        _return_stack(stack)
        click.echo("")

@stacks.command(name="id", help="Get a stack by ID")
@click.pass_context
@click.argument("id", type=click.INT)
def get_stack_by_id(ctx: click.Context, id: int):
    client = ctx.obj["client"]
    response = client.get(f"/stack/{id}")
    if response.status_code != 200:
        click.echo(red("Failed to get stack", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return

    _return_stack(response.json()["stack"])

@stacks.command(name="create", help="Create a new stack")
@click.pass_context
@click.option("--name", type=click.STRING, required=False, help="Name of the stack")
@click.option("--description", type=click.STRING, required=False, help="Description of the stack")
@click.option("--supervisor-id", type=click.INT, required=False, help="Supervisor agent ID")
@click.option("--supporting-id", "supporting_ids", type=click.INT, multiple=True, help="Supporting agent ID (repeatable)")
@click.option("--interactive/--no-interactive", default=True, help="Use interactive selection prompts")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def create_stack(ctx: click.Context, name: str | None, description: str | None, supervisor_id: int | None, supporting_ids: tuple[int, ...], interactive: bool, yes: bool):
    client = ctx.obj["client"]

    click.echo(green("Stack creation wizard", "bold"))
    click.echo("")
    click.echo(white("Step 1/4 - Stack details", "normal"))
    click.echo("")
    if not name:
        name = click.prompt("Stack name", type=str)
    if not description:
        description = click.prompt("Stack description", type=str)

    supervisors, supporting_agents = get_agents_by_type(ctx)
    if supervisors is None or supporting_agents is None:
        return
    if not supervisors:
        click.echo(red("No supervisor agents found", "bold"))
        click.echo(white("Create one first with `astro agents create`.", "normal"))
        return
    if not supporting_agents:
        click.echo(red("No supporting agents found", "bold"))
        click.echo(white("Create at least one first with `astro agents create`.", "normal"))
        return

    click.echo("")
    click.echo(white("Step 2/4 - Supervisor selection", "normal"))
    click.echo("")
    valid_supervisor_ids = {agent["id"] for agent in supervisors}
    if supervisor_id is None:
        supervisor_choice = select_one(
            "Select supervisor",
            [(str(agent["id"]), f"{agent['name']} ({agent['role']})") for agent in supervisors],
            interactive=interactive,
        )
        supervisor_id = int(supervisor_choice)
    elif supervisor_id not in valid_supervisor_ids:
        click.echo(red(f"Supervisor ID {supervisor_id} is not a valid supervisor agent.", "bold"))
        return

    click.echo("")
    click.echo(white("Step 3/4 - Supporting selection", "normal"))
    click.echo("")
    selected_supporting_ids = [*supporting_ids]
    valid_supporting_ids = {agent["id"] for agent in supporting_agents}
    if not selected_supporting_ids:
        selected_supporting_ids = select_many_ids(
            "Select supporting agents",
            [(agent["id"], f"{agent['name']} ({agent['role']})") for agent in supporting_agents],
            interactive=interactive,
        )
    elif any(agent_id not in valid_supporting_ids for agent_id in selected_supporting_ids):
        click.echo(red("One or more --supporting-id values are not supporting agents.", "bold"))
        return

    if not selected_supporting_ids:
        click.echo(red("At least one supporting agent is required.", "bold"))
        return

    click.echo("")
    click.echo(white("Step 4/4 - Review", "normal"))
    click.echo(f"{green('Name:', 'bold')} {name}")
    click.echo(f"{green('Description:', 'bold')} {description}")
    click.echo(f"{green('Supervisor ID:', 'bold')} {supervisor_id}")
    click.echo(f"{green('Supporting IDs:', 'bold')} {selected_supporting_ids}")
    click.echo("")

    if not yes and not click.confirm("Create this stack?", default=True):
        click.echo(white("Cancelled.", "normal"))
        return

    payload = {
        "name": name,
        "description": description,
        "supervisor": supervisor_id,
        "supporting": selected_supporting_ids,
    }
    response = client.post("/stack/create", json=payload)
    if response.status_code != 200:
        click.echo(red("Failed to create stack", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return

    click.echo(green("Stack created successfully", "bold"))
    _return_stack(response.json()["stack"])

@stacks.command(name="delete", help="Delete a stack")
@click.pass_context
@click.argument("id", type=click.INT)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def delete_stack(ctx: click.Context, id: int, yes: bool):
    client = ctx.obj["client"]

    click.echo(green("Stack deletion wizard", "bold"))
    click.echo("")
    click.echo(white("Step 1/1 - Review", "normal"))
    click.echo(f"{green('ID:', 'bold')} {id}")
    click.echo("")

    if not yes and not click.confirm("Delete this stack?", default=True):
        click.echo(white("Cancelled.", "normal"))
        return

    response = client.delete(f"/stack/{id}")
    if response.status_code != 200:
        click.echo(red("Failed to delete stack", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return

    click.echo(green("Stack deleted successfully", "bold"))

@stacks.command(name="exec", help="Execute a stack")
@click.pass_context
@click.option("--verbose", "--v", is_flag=True, help="Verbose output including agent and tool calls")
@click.argument("id", type=click.INT)
def execute_stack(ctx: click.Context, id: int, verbose: bool):
    sync_client = ctx.obj["client"]

    user_response = sync_client.get("/auth/user/me")
    user = user_response.json()["user"]
    username = user["username"]
    
    if verbose:
        click.echo(green("Verbose output enabled", "bold"))
        click.echo("")

    stack_response = sync_client.get(f"/stack/{id}")
    if stack_response.status_code != 200:
        click.echo(red("Failed to load stack", "bold"))
        click.echo(white(f"Error: {stack_response.text}", "normal"))
        return
    stack = stack_response.json()["stack"]
    agents = stack.get("agents") or []
    supervisors = [a for a in agents if a.get("agent_type") == "supervisor"]
    name = supervisors[0]["name"] if supervisors else stack["name"]

    click.echo(green("____________________________________________________________", "bold"))
    click.echo(f"{green('Stack:', 'bold')} {stack['name']}")
    click.echo(f"{green('Description:', 'bold')} {stack['description']}")
    click.echo(f"{green('Created:', 'bold')} {stack['created']}")
    click.echo("")
    click.echo(f"{green('Supervisor:', 'bold')} {supervisors[0]['name']}")
    click.echo(f"{green('Supporting:', 'bold')} {', '.join([a['name'] for a in agents if a.get('agent_type') == 'supporting'])}")
    click.echo(green("____________________________________________________________", "bold"))
    click.echo("")

    while True:
        try:
            input = click.prompt(magenta(f"{username}@astro", "bold"))
        except (click.Abort, EOFError, KeyboardInterrupt):
            break
        
        message = input.strip()

        if not message:
            continue

        cmd = message.lower()

        if cmd in (_chat_commands.keys()):
            if cmd == "/exit" or cmd == "/quit" or cmd == "/q":
                break
            elif cmd == "/clear":
                click.clear()
            elif cmd == "/history" or cmd == "/h":
                response = sync_client.post("/message/history", json={"stack_id": id, "limit": 10, "offset": 0})
                if response.status_code != 200:
                    click.echo(red("Failed to get message history", "bold"))
                    click.echo(white(f"Error: {response.text}", "normal"))
                    continue
                messages = response.json()["messages"]
                for message in messages:
                    if message["role"] == "assistant":
                        click.echo(f"{cyan(f"{message['role'].capitalize()}:", "bold")} {white(f"{message['content']}", "normal")}")
                    elif message["role"] == "user":
                        click.echo(f"{magenta(f"{username}@astro:", "bold")} {white(f"{message['content']}", "normal")}")
                    click.echo("")
            elif cmd == "/help" or cmd == "/h":
                for command, description in _chat_commands.items():
                    click.echo(f"{green(f"{command}:", "bold")} {white(f"{description}", "normal")}")
            elif cmd == "/info" or cmd == "/i":
                response = sync_client.get(f"/stack/{id}")
                if response.status_code != 200:
                    click.echo(red("Failed to get stack info", "bold"))
                    click.echo(white(f"Error: {response.text}", "normal"))
                    continue
                stack = response.json()["stack"]
                click.echo(f"{cyan('Name:', 'bold')} {stack['name']}")
                click.echo(f"{cyan('Description:', 'bold')} {stack['description']}")
                click.echo(f"{cyan('Created:', 'bold')} {stack['created']}")
            continue
        click.secho("")

        asyncio.run(stream(ctx, id, message, name, verbose=verbose))

    click.echo("")
    click.echo(white("Exiting chat...", "bold"))