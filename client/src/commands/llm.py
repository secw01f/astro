import click

from lib.color import cyan, green, red, white

@click.group(help="Manage ASTRO LLMs")
def llms():
    pass

@llms.command(name="list", help="List all LLMs")
@click.pass_context
def list_llms(ctx: click.Context):
    client = ctx.obj["client"]
    response = client.get("/llm/llms")
    if response.status_code != 200:
        click.echo(f"Failed to list LLMs: {response.text}")

    llms = response.json()["llms"]

    if not llms:
        click.echo(f"{red("No LLMs found", "bold")}")
        click.echo(f"{white("Use `astro llms create` to create a new LLM", "normal")}")
        return

    for llm in llms:
        click.echo(f"{cyan("ID:", "bold")} {llm['id']}\n{cyan("Name:", "bold")} {llm['name']}\n{cyan("Provider:", "bold")} {llm['provider']}\n{cyan("Created:", "bold")} {llm['created']}")
        click.echo("\n")

@llms.command(name="id", help="Get a LLM by ID")
@click.pass_context
@click.argument("id", type=click.INT)
def get_llm_by_id(ctx: click.Context, id: int):
    client = ctx.obj["client"]
    response = client.get(f"/llm/{id}")

    llm = response.json()["llm"]
    if not llm:
        click.echo(f"{red("LLM not found", "bold")}")
        return
    
    click.echo(f"{cyan("ID:", "bold")} {llm['id']}\n{cyan("Name:", "bold")} {llm['name']}\n{cyan("Provider:", "bold")} {llm['provider']}\n{cyan("Created:", "bold")} {llm['created']}")

@llms.command(name="create", help="Create a new LLM")
@click.pass_context
@click.option("--name", type=str, required=True, help="The name of the LLM")
@click.option("--provider", type=click.Choice(["anthropic", "openai", "bedrock"]), required=True, help="The provider of the LLM")
@click.option("--model", type=str, required=True, help="The model of the LLM")
@click.option("--max-tokens", type=int, help="The max tokens of the LLM")
def create(ctx: click.Context, name: str, provider: str, model: str, max_tokens: int | None = None):
    client = ctx.obj["client"]

    if provider == "anthropic" or provider == "openai":
        key = click.prompt("Key", type=str, hide_input=True)
        if max_tokens is not None:
            response = client.post("/llm/new", json={"name": name, "provider": provider, "key": key, "model": model, "max_tokens": max_tokens})
        else:
            response = client.post("/llm/new", json={"name": name, "provider": provider, "key": key, "model": model})
    elif provider == "bedrock":
        key = click.prompt("Access Key", type=str, hide_input=True)
        key_id = click.prompt("Key ID", type=str)
        region = click.prompt("Region", type=str)
        click.echo(
            "For newer Claude models (e.g. anthropic.claude-opus-4-6-v1), use the base model ID; "
            "ASTRO will map it to a regional inference profile (e.g. us.anthropic.claude-opus-4-6-v1)."
        )
        if max_tokens is not None:
            response = client.post("/llm/new", json={"name": name, "provider": provider, "key": key, "key_id": key_id, "model": model, "max_tokens": max_tokens, "region": region})
        else:
            response = client.post("/llm/new", json={"name": name, "provider": provider, "key": key, "key_id": key_id, "model": model, "region": region})

    if response.status_code != 200:
        click.echo(f"Failed to create LLM: {response.text}")
        return

    llm = response.json()["llm"]
    click.echo(f"{green("ID:", "bold")} {llm['id']}\n{green("Name:", "bold")} {llm['name']}\n{green("Provider:", "bold")} {llm['provider']}\n{green("Created:", "bold")} {llm['created']}")

@llms.command(name="update", help="Update a LLM")
@click.pass_context
@click.option("--name", type=str, required=False, help="The name of the LLM")
@click.option("--provider", type=click.Choice(["anthropic", "openai", "bedrock"]), required=True, help="The provider of the LLM")
@click.option("--model", type=str, required=False, help="The model of the LLM")
@click.option("--max-tokens", type=int, required=False, help="The max tokens of the LLM")
@click.argument("id", type=click.INT)
def update_llm(ctx: click.Context, id: int, name: str | None = None, provider: str | None = None, model: str | None = None, max_tokens: int | None = None, key: str | None = None):
    if not key:
        update_prompt = click.prompt("Update Key? (Y/n)", type=str, default="n")
        if update_prompt.strip().lower() == "y":
            key = click.prompt("Key", type=str, hide_input=True)

    client = ctx.obj["client"]

    payload = {}
    
    if name:
        payload["name"] = name
    if key:
        payload["key"] = key
    if provider:
        payload["provider"] = provider
    if model:
        payload["model"] = model
    if max_tokens:
        payload["max_tokens"] = max_tokens

    response = client.patch(f"/llm/{id}", json=payload)
    if response.status_code != 200:
        click.echo(red("Failed to update LLM", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return

    llm = response.json()["llm"]

    click.echo(f"{green("ID:", "bold")} {llm['id']}\n{green("Name:", "bold")} {llm['name']}\n{green("Provider:", "bold")} {llm['provider']}\n{green("Created:", "bold")} {llm['created']}")

@llms.command(name="delete", help="Delete a LLM")
@click.pass_context
@click.argument("id", type=click.INT)
def delete_llm(ctx: click.Context, id: int):
    client = ctx.obj["client"]

    delete_response = client.delete(f"/llm/{id}")

    if delete_response.status_code != 200:
        click.echo(red("Failed to delete LLM", "bold"))
        click.echo(white(f"Error: {delete_response.text}", "normal"))
        return

    click.echo(green("LLM deleted successfully", "bold"))