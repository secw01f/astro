from typing import Any

import click

from lib.color import cyan, green, red, white, yellow
from lib.wizard import select_one, select_many_ids

SUPERVISOR_ROLES = [
    "application_security_supervisor",
    "governance_risk_compliance_supervisor",
    "detection_incident_response_supervisor",
    "offensive_security_supervisor",
    "vulnerability_management_supervisor",
    "custom_supervisor",
]

SUPPORTING_ROLES = [
    "application_security_architect",
    "detection_incident_response_architect",
    "security_engineering_architect",
    "application_security_engineer",
    "governance_risk_compliance_engineer",
    "detection_incident_response_engineer",
    "offensive_security_engineer",
    "vulnerability_management_engineer",
    "application_security_analyst",
    "governance_risk_compliance_analyst",
    "detection_incident_response_analyst",
    "offensive_security_analyst",
    "vulnerability_management_analyst",
    "custom_supporting_agent",
]


def _truncate_prompt(text: str, limit: int = 72) -> str:
    return text if len(text) <= limit else f"{text[:limit - 3]}..."

def _is_tty_interactive(interactive: bool) -> bool:
    return interactive and click.get_text_stream("stdin").isatty()

def _prompt_keep_or_change(label: str, current_display: str, *, interactive: bool) -> bool:
    """Return True to keep the current value."""
    if not _is_tty_interactive(interactive):
        return True
    choice = select_one(
        label,
        [
            ("keep", f"Keep current - {current_display}"),
            ("change", "Change"),
        ],
        interactive=interactive,
    )
    return choice == "keep"

def _return_agent(agent: dict[str, Any]) -> None:
    llm = agent.get("llm")
    llm_line = (
        f"{llm['name']} ({llm['provider']})"
        if isinstance(llm, dict)
        else "(none)"
    )
    click.echo(
        f"{cyan('ID:', 'bold')} {agent['id']}\n"
        f"{cyan('Name:', 'bold')} {agent['name']}\n"
        f"{cyan('Type:', 'bold')} {agent['agent_type']}\n"
        f"{cyan('LLM:', 'bold')} {llm_line}\n"
        f"{cyan('Role:', 'bold')} {agent['role']}\n"
        f"{cyan('System Prompt:', 'bold')} {agent['system_prompt']}\n"
        f"{cyan('Stacks:', 'bold')} {agent['stacks']}\n"
        f"{cyan('Toolsets:', 'bold')} {agent['toolsets']}\n"
        f"{cyan('Created:', 'bold')} {agent['created']}"
    )

@click.group(help="Manage ASTRO agents")
def agents():
    pass

@agents.command(name="list")
@click.pass_context
def list_agents(ctx: click.Context):
    client = ctx.obj["client"]
    response = client.get("/agent/agents")
    if response.status_code != 200:
        click.echo(red("Failed to list agents", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return

    agents_data = response.json()["agents"]
    if not agents_data:
        click.echo(red("No agents available", "bold"))
        click.echo(white("Use `astro agent create` to create an agent", "normal"))
        return

    for agent in agents_data:
        _return_agent(agent)
        click.echo("")


@agents.command(name="id")
@click.pass_context
@click.argument("id", type=click.INT)
def get_agent_by_id(ctx: click.Context, id: int):
    client = ctx.obj["client"]
    response = client.get(f"/agent/{id}")
    if response.status_code != 200:
        click.echo(red("Agent not found", "bold"))
        return
    _return_agent(response.json()["agent"])


@agents.command()
@click.pass_context
@click.option("--name", type=click.STRING, required=False, help="Name of the agent")
@click.option("--description", type=click.STRING, required=False, help="Description of the agent")
@click.option("--type", "agent_type", type=click.Choice(["supporting", "supervisor"]), required=False, help="Type of agent")
@click.option("--role", type=click.STRING, required=False, help="Role of the agent")
@click.option("--system-prompt", type=click.STRING, required=False, help="System prompt for the agent")
@click.option("--llm-id", type=click.INT, required=False, help="LLM ID to use")
@click.option("--toolset-id", "toolset_ids", type=click.INT, multiple=True, help="Toolset ID to attach (repeatable)")
@click.option("--interactive/--no-interactive", default=True, help="Use interactive selection prompts")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def create(ctx: click.Context, name: str | None, description: str | None, agent_type: str | None, role: str | None, system_prompt: str | None, llm_id: int | None, toolset_ids: tuple[int, ...], interactive: bool, yes: bool):
    client = ctx.obj["client"]

    click.echo(green("Agent creation wizard", "bold"))
    click.echo("")
    click.echo(white("Step 1/5 - Agent details", "normal"))
    click.echo("")
    if not name:
        name = click.prompt("Agent name", type=str)
    if not description:
        description = click.prompt("Agent description", type=str)
    if not agent_type:
        agent_type = select_one(
            "Select agent type",
            [("supporting", "Supporting"), ("supervisor", "Supervisor")],
            interactive=interactive,
        )

    click.echo("")
    click.echo(white("Step 2/5 - Role", "normal"))
    click.echo("")
    allowed_roles = SUPERVISOR_ROLES if agent_type == "supervisor" else SUPPORTING_ROLES
    if role and role not in allowed_roles:
        click.echo(red(f"Role '{role}' does not match type '{agent_type}'.", "bold"))
        role = None
    if not role:
        role_choices = [(value, value.replace("_", " ")) for value in allowed_roles]
        role = select_one("Select role", role_choices, interactive=interactive)

    click.echo("")
    click.echo(white("Step 3/5 - LLM selection", "normal"))
    click.echo("")
    llm_response = client.get("/llm/llms")
    if llm_response.status_code != 200:
        click.echo(red("Failed to list LLMs", "bold"))
        click.echo(white(f"Error: {llm_response.text}", "normal"))
        return

    llms = llm_response.json().get("llms", [])
    if not llms:
        click.echo(red("No LLMs found. Create one first with `astro llms create`.", "bold"))
        return

    llm_choices = [
        (llm["id"], f"{llm['name']} ({llm['provider']})")
        for llm in llms
    ]
    llm_ids = {item_id for item_id, _ in llm_choices}
    if llm_id is None:
        llm_choice = select_one(
            "Select LLM",
            [(str(item_id), f"{item_id}: {label}") for item_id, label in llm_choices],
            interactive=interactive,
        )
        llm_id = int(llm_choice)
    elif llm_id not in llm_ids:
        click.echo(red(f"LLM ID {llm_id} not found.", "bold"))
        return

    click.echo("")
    if agent_type == "supervisor":
        click.echo(white("Step 4/5 - Prompt", "normal"))
    else:
        click.echo(white("Step 4/5 - Prompt and toolsets", "normal"))
    click.echo("")

    if not system_prompt and role in ("custom_supervisor", "custom_supporting_agent"):
        system_prompt = click.prompt("System prompt", type=str)
    else:
        system_prompt = None
    click.echo("")

    selected_toolset_ids: list[int] = []
    if agent_type == "supervisor":
        if toolset_ids:
            click.echo(
                yellow(
                    "Ignoring --toolset-id: supervisors do not use toolsets at creation.",
                    "bold",
                )
            )
    else:
        selected_toolset_ids = list(toolset_ids)
        toolset_response = client.get("/tool/toolsets")
        if toolset_response.status_code == 200 and not selected_toolset_ids:
            toolsets = toolset_response.json().get("toolsets", [])
            toolset_choices = [
                (toolset["id"], f"{toolset['name']} ({toolset['type']})")
                for toolset in toolsets
            ]
            selected_toolset_ids = select_many_ids(
                "Select toolsets (optional)",
                toolset_choices,
                interactive=interactive,
            )
        elif toolset_response.status_code != 200 and not selected_toolset_ids:
            click.echo(yellow("Could not list toolsets; continuing without any.", "bold"))

    click.echo("")
    click.echo(white("Step 5/5 - Review", "normal"))
    click.echo(f"{green('Name:', 'bold')} {name}")
    click.echo(f"{green('Description:', 'bold')} {description}")
    click.echo(f"{green('Type:', 'bold')} {agent_type}")
    click.echo(f"{green('Role:', 'bold')} {role}")
    click.echo(f"{green('LLM ID:', 'bold')} {llm_id}")
    click.echo(f"{green('System Prompt:', 'bold')} {system_prompt}")
    if agent_type == "supervisor":
        click.echo(f"{green('Toolsets:', 'bold')} (none — supervisors coordinate supporting agents)")
    else:
        click.echo(f"{green('Toolset IDs:', 'bold')} {selected_toolset_ids or '(none)'}")
    click.echo("")

    if not yes and not click.confirm("Create this agent?", default=True):
        click.echo(white("Cancelled.", "normal"))
        return

    payload = {
        "name": name,
        "description": description,
        "system_prompt": system_prompt,
        "llm": llm_id,
        "type": agent_type,
        "role": role,
        "toolset_ids": selected_toolset_ids if agent_type != "supervisor" else None,
    }

    create_response = client.post("/agent/create", json=payload)
    if create_response.status_code != 200:
        click.echo(red("Failed to create agent", "bold"))
        click.echo(white(f"Error: {create_response.text}", "normal"))
        return

    click.echo(green("Agent created successfully", "bold"))
    _return_agent(create_response.json()["agent"])

@agents.command(name="update")
@click.pass_context
@click.argument("id", type=click.INT)
@click.option("--name", type=click.STRING, required=False, help="Name of the agent")
@click.option("--description", type=click.STRING, required=False, help="Description of the agent")
@click.option("--role", type=click.STRING, required=False, help="Role of the agent")
@click.option("--system-prompt", type=click.STRING, required=False, help="System prompt for the agent")
@click.option("--llm-id", type=click.INT, required=False, help="LLM ID to use")
@click.option("--toolset-id", "toolset_ids", type=click.INT, multiple=True, help="Toolset ID to attach (repeatable)")
@click.option("--interactive/--no-interactive", default=True, help="Use interactive selection prompts")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def update_agent(ctx: click.Context, id: int, name: str | None, description: str | None, role: str | None, system_prompt: str | None, llm_id: int | None, toolset_ids: tuple[int, ...], interactive: bool, yes: bool):
    client = ctx.obj["client"]

    click.echo(green("Agent update wizard", "bold"))
    click.echo("")

    current_agent_details = client.get(f"/agent/{id}")
    if current_agent_details.status_code != 200:
        click.echo(red("Failed to get agent details", "bold"))
        click.echo(white(f"Error: {current_agent_details.text}", "normal"))
        return
    current_agent = current_agent_details.json()["agent"]

    _return_agent(current_agent)
    click.echo("")

    current_name = current_agent["name"]
    current_description = current_agent["description"]
    current_role = current_agent["role"]
    current_prompt = current_agent.get("system_prompt", "")
    current_llm = current_agent.get("llm")
    if isinstance(current_llm, dict):
        current_llm_id = current_llm["id"]
        current_llm_display = f"{current_llm['name']} ({current_llm['provider']})"
    else:
        current_llm_id = None
        current_llm_display = "(none)"
    current_toolsets = current_agent.get("toolsets", [])
    current_toolset_ids = [toolset["id"] for toolset in current_toolsets]
    current_toolset_display = (
        ", ".join(f"{toolset['id']}: {toolset['name']}" for toolset in current_toolsets)
        or "(none)"
    )

    updates: dict[str, Any] = {}
    allowed_roles = (
        SUPERVISOR_ROLES if current_agent["agent_type"] == "supervisor" else SUPPORTING_ROLES
    )
    role_choices = [(value, value.replace("_", " ")) for value in allowed_roles]

    click.echo(white("Step 1/5 - Agent details", "normal"))
    click.echo("")
    if name is not None:
        updates["name"] = name
    elif not _prompt_keep_or_change("Name", current_name, interactive=interactive):
        updates["name"] = click.prompt("Agent name", type=str, default=current_name)

    if description is not None:
        updates["description"] = description
    elif not _prompt_keep_or_change("Description", current_description, interactive=interactive):
        updates["description"] = click.prompt(
            "Agent description", type=str, default=current_description
        )

    if role is not None:
        if role not in allowed_roles:
            click.echo(red(f"Role '{role}' does not match type '{current_agent['agent_type']}'.", "bold"))
            return
        updates["role"] = role
    elif not _prompt_keep_or_change(
        "Role", current_role.replace("_", " "), interactive=interactive
    ):
        updates["role"] = select_one("Select role", role_choices, interactive=interactive)

    click.echo("")
    click.echo(white("Step 2/5 - System prompt", "normal"))
    click.echo("")
    prompt_display = _truncate_prompt(current_prompt) if current_prompt else "(empty prompt)"
    if system_prompt is not None:
        updates["system_prompt"] = system_prompt
    elif not _prompt_keep_or_change("System prompt", prompt_display, interactive=interactive):
        updates["system_prompt"] = click.prompt(
            "System prompt", type=str, default=current_prompt, show_default=bool(current_prompt)
        )

    click.echo("")
    click.echo(white("Step 3/5 - LLM selection", "normal"))
    click.echo("")
    if llm_id is not None:
        updates["llm"] = llm_id
    elif not _prompt_keep_or_change("LLM", current_llm_display, interactive=interactive):
        llm_response = client.get("/llm/llms")
        if llm_response.status_code != 200:
            click.echo(red("Failed to list LLMs", "bold"))
            click.echo(white(f"Error: {llm_response.text}", "normal"))
            return

        llms = llm_response.json().get("llms", [])
        if not llms:
            click.echo(red("No LLMs found. Create one first with `astro llms create`.", "bold"))
            return

        llm_choices = [
            (llm["id"], f"{llm['name']} ({llm['provider']})")
            for llm in llms
        ]
        llm_choice = select_one(
            "Select LLM",
            [(str(item_id), f"{item_id}: {label}") for item_id, label in llm_choices],
            interactive=interactive,
        )
        updates["llm"] = int(llm_choice)

    click.echo("")
    click.echo(white("Step 4/5 - Toolset selection", "normal"))
    click.echo("")
    if toolset_ids:
        updates["toolset_ids"] = list(toolset_ids)
    elif not _prompt_keep_or_change("Toolsets", current_toolset_display, interactive=interactive):
        toolset_response = client.get("/tool/toolsets")
        if toolset_response.status_code != 200:
            click.echo(red("Failed to list toolsets", "bold"))
            click.echo(white(f"Error: {toolset_response.text}", "normal"))
            return
        toolsets = toolset_response.json().get("toolsets", [])
        toolset_choices = [
            (toolset["id"], f"{toolset['name']} ({toolset['type']})")
            for toolset in toolsets
        ]
        updates["toolset_ids"] = select_many_ids(
            "Select toolsets (optional)",
            toolset_choices,
            interactive=interactive,
        )

    if llm_id is not None and "llm" in updates:
        llm_response = client.get("/llm/llms")
        if llm_response.status_code == 200:
            llm_ids = {llm["id"] for llm in llm_response.json().get("llms", [])}
            if updates["llm"] not in llm_ids:
                click.echo(red(f"LLM ID {updates['llm']} not found.", "bold"))
                return

    if not updates:
        click.echo(white("No changes selected.", "normal"))
        return

    final_name = updates.get("name", current_name)
    final_description = updates.get("description", current_description)
    final_role = updates.get("role", current_role)
    final_prompt = updates.get("system_prompt", current_prompt)
    final_llm_id = updates.get("llm", current_llm_id)
    final_toolset_ids = updates.get("toolset_ids", current_toolset_ids)

    click.echo("")
    click.echo(white("Step 5/5 - Review", "normal"))
    click.echo(f"{green('Name:', 'bold')} {final_name}")
    click.echo(f"{green('Description:', 'bold')} {final_description}")
    click.echo(f"{green('Role:', 'bold')} {final_role}")
    click.echo(f"{green('LLM ID:', 'bold')} {final_llm_id}")
    click.echo(f"{green('System Prompt:', 'bold')} {final_prompt}")
    click.echo(f"{green('Toolset IDs:', 'bold')} {final_toolset_ids}")
    click.echo("")

    if not yes and not click.confirm("Update this agent?", default=True):
        click.echo(white("Cancelled.", "normal"))
        return

    update_response = client.patch(f"/agent/{id}", json=updates)
    if update_response.status_code != 200:
        click.echo(red("Failed to update agent", "bold"))
        click.echo(white(f"Error: {update_response.text}", "normal"))
        return

    click.echo("")
    click.echo(green("Agent updated successfully", "bold"))
    click.echo("")
    _return_agent(update_response.json()["agent"])

@agents.command(name="delete")
@click.pass_context
@click.argument("id", type=click.INT)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def delete_agent(ctx: click.Context, id: int, yes: bool):
    client = ctx.obj["client"]

    click.echo(green("Agent deletion wizard", "bold"))
    click.echo("")
    click.echo(white("Step 1/1 - Review", "normal"))
    click.echo(f"{green('ID:', 'bold')} {id}")
    click.echo("")

    if not yes and not click.confirm("Delete this agent?", default=True):
        click.echo(white("Cancelled.", "normal"))
        return

    delete_response = client.delete(f"/agent/{id}")
    if delete_response.status_code != 200:
        click.echo(red("Failed to delete agent", "bold"))
        click.echo(white(f"Error: {delete_response.text}", "normal"))
        return

    click.echo(green("Agent deleted successfully", "bold")) 