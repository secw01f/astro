import click

from lib.color import cyan, green, red, white
from lib.wizard import select_many_ids, select_one

from lib.stack import (
    format_duration,
    format_recurrence_day,
    format_schedule,
    format_schedule_run,
    format_run_messages,
    get_agents_by_type,
    parse_duration,
    parse_run_times,
    WEEKDAY_NAMES,
)
from src.tui.stack_exec import StackExecApp

def _return_stack(stack: dict) -> None:
    click.echo(
        f"{cyan('ID:', 'bold')} {stack['id']}\n"
        f"{cyan('Name:', 'bold')} {stack['name']}\n"
        f"{cyan('Description:', 'bold')} {stack['description']}\n"
        f"{cyan('Created:', 'bold')} {stack['created']}"
    )

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

    stack_response = sync_client.get(f"/stack/{id}")
    if stack_response.status_code != 200:
        click.echo(red("Failed to load stack", "bold"))
        click.echo(white(f"Error: {stack_response.text}", "normal"))
        return
    stack = stack_response.json()["stack"]
    agents = stack.get("agents") or []
    supervisors = [a for a in agents if a.get("agent_type") == "supervisor"]
    name = supervisors[0]["name"] if supervisors else stack["name"]
    supporting_names = [a["name"] for a in agents if a.get("agent_type") == "supporting"]

    url = ctx.obj["url"]
    token = sync_client.headers.get("X-API-KEY")

    StackExecApp(
        base_url=url,
        token=token,
        stack_id=id,
        stack_name=stack["name"],
        stack_description=stack.get("description") or "",
        supervisor_name=name,
        supporting_names=supporting_names,
        username=username,
        verbose=verbose,
    ).run()

    click.echo("")
    click.echo(white("Exiting chat...", "bold"))


@stacks.group(name="schedule", help="Manage stack schedules")
def schedule():
    pass


def _select_stack_id(ctx: click.Context, stack_id: int | None, *, interactive: bool) -> int | None:
    client = ctx.obj["client"]
    if stack_id is not None:
        response = client.get(f"/stack/{stack_id}")
        if response.status_code != 200:
            click.echo(red("Failed to load stack", "bold"))
            click.echo(white(f"Error: {response.text}", "normal"))
            return None
        return stack_id

    response = client.get("/stack/stacks")
    if response.status_code != 200:
        click.echo(red("Failed to list stacks", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return None

    stacks_data = response.json().get("stacks", [])
    if not stacks_data:
        click.echo(red("No stacks found", "bold"))
        click.echo(white("Create one first with `astro stack create`.", "normal"))
        return None

    choice = select_one(
        "Select stack",
        [(str(stack["id"]), f"{stack['name']} ({stack['description']})") for stack in stacks_data],
        interactive=interactive,
    )
    return int(choice)


def _load_schedules(ctx: click.Context) -> list[dict] | None:
    client = ctx.obj["client"]
    response = client.get("/stack/schedules")
    if response.status_code != 200:
        click.echo(red("Failed to list schedules", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return None
    return response.json().get("schedules", [])


def _select_schedule_id(
    ctx: click.Context,
    schedule_id: int | None,
    *,
    interactive: bool,
) -> int | None:
    client = ctx.obj["client"]
    if schedule_id is not None:
        response = client.get(f"/stack/schedule/{schedule_id}")
        if response.status_code != 200:
            click.echo(red("Failed to load schedule", "bold"))
            click.echo(white(f"Error: {response.text}", "normal"))
            return None
        return schedule_id

    schedules = _load_schedules(ctx)
    if schedules is None:
        return None
    if not schedules:
        click.echo(red("No schedules found", "bold"))
        click.echo(white("Use `astro stack schedule create` to create one.", "normal"))
        return None

    choice = select_one(
        "Select schedule",
        [
            (
                str(item["id"]),
                f"{item['name']} (stack {item['stack_id']}, {item['schedule_type']})",
            )
            for item in schedules
        ],
        interactive=interactive,
    )
    return int(choice)


def _select_schedule_run_id(
    ctx: click.Context,
    schedule_id: int | None,
    run_id: str | None,
    *,
    interactive: bool,
) -> str | None:
    if run_id is not None:
        return run_id

    selected_schedule_id = _select_schedule_id(ctx, schedule_id, interactive=interactive)
    if selected_schedule_id is None:
        return None

    client = ctx.obj["client"]
    response = client.get(
        f"/stack/schedule/{selected_schedule_id}/runs",
        params={"limit": 50, "offset": 0},
    )
    if response.status_code != 200:
        click.echo(red("Failed to list schedule runs", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return None

    runs = response.json().get("runs", [])
    if not runs:
        click.echo(red("No runs found for this schedule", "bold"))
        return None

    choice = select_one(
        "Select run",
        [
            (
                item["run_id"],
                f"{item['status']} - started {item['started_at']}",
            )
            for item in runs
        ],
        interactive=interactive,
    )
    return choice


@schedule.command(name="list", help="List all schedules")
@click.pass_context
def list_schedules(ctx: click.Context):
    client = ctx.obj["client"]
    response = client.get("/stack/schedules")
    if response.status_code != 200:
        click.echo(red("Failed to list schedules", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return

    schedules = response.json().get("schedules", [])
    if not schedules:
        click.echo(red("No schedules found", "bold"))
        click.echo(white("Use `astro stack schedule create` to create one.", "normal"))
        return

    for item in schedules:
        click.echo(format_schedule(item))
        click.echo("")


@schedule.command(name="get", help="Get a schedule by ID")
@click.pass_context
@click.option("--id", "schedule_id", type=click.INT, help="Schedule ID")
@click.option("--interactive/--no-interactive", default=True, help="Use interactive selection when ID is omitted")
def get_schedule(ctx: click.Context, schedule_id: int | None, interactive: bool):
    schedule_id = _select_schedule_id(ctx, schedule_id, interactive=interactive)
    if schedule_id is None:
        return

    client = ctx.obj["client"]
    response = client.get(f"/stack/schedule/{schedule_id}")
    if response.status_code != 200:
        click.echo(red("Failed to get schedule", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return

    click.echo(format_schedule(response.json()["schedule"]))


@schedule.command(name="create", help="Create a new schedule")
@click.pass_context
@click.option("--stack-id", type=click.INT, help="Stack ID to run")
@click.option("--name", type=click.STRING, help="Schedule name")
@click.option("--message", type=click.STRING, help="Prompt sent on each run")
@click.option(
    "--type",
    "schedule_type",
    type=click.Choice(["interval", "fixed", "recurring"], case_sensitive=False),
    help="Schedule type",
)
@click.option("--every", type=click.STRING, help="Interval duration, e.g. 30m, 2h, 1d, 1w")
@click.option("--interval-seconds", type=click.INT, help="Interval in seconds (min 60)")
@click.option(
    "--run-at",
    "run_at_values",
    multiple=True,
    help="Fixed run time in ISO format (repeatable)",
)
@click.option(
    "--recurrence",
    type=click.Choice(["weekly", "monthly"], case_sensitive=False),
    help="Recurring cadence",
)
@click.option(
    "--recurrence-day",
    type=click.INT,
    help="Weekly: 0=Monday..6=Sunday. Monthly: day of month 1-31",
)
@click.option("--recurrence-hour", type=click.IntRange(0, 23), default=0, show_default=True)
@click.option("--recurrence-minute", type=click.IntRange(0, 59), default=0, show_default=True)
@click.option("--enabled/--disabled", default=True, show_default=True)
@click.option("--verbose", is_flag=True, help="Include agent and tool output in scheduled runs")
@click.option("--interactive/--no-interactive", default=True, help="Use interactive prompts")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def create_schedule(
    ctx: click.Context,
    stack_id: int | None,
    name: str | None,
    message: str | None,
    schedule_type: str | None,
    every: str | None,
    interval_seconds: int | None,
    run_at_values: tuple[str, ...],
    recurrence: str | None,
    recurrence_day: int | None,
    recurrence_hour: int,
    recurrence_minute: int,
    enabled: bool,
    verbose: bool,
    interactive: bool,
    yes: bool,
):
    client = ctx.obj["client"]

    click.echo(green("Schedule creation wizard", "bold"))
    click.echo("")

    stack_id = _select_stack_id(ctx, stack_id, interactive=interactive)
    if stack_id is None:
        return

    if not name:
        name = click.prompt("Schedule name", type=str)
    if not message:
        message = click.prompt("Run message", type=str)
    if schedule_type is None:
        schedule_type = select_one(
            "Schedule type",
            [
                ("interval", "Interval - run every N seconds/minutes/hours/days/weeks"),
                ("fixed", "Fixed - run at specific datetimes"),
                ("recurring", "Recurring - run weekly or monthly"),
            ],
            interactive=interactive,
        )

    payload: dict = {
        "stack_id": stack_id,
        "name": name,
        "message": message,
        "schedule_type": schedule_type,
        "enabled": enabled,
        "verbose": verbose,
    }

    try:
        if schedule_type == "interval":
            if interval_seconds is None and every:
                interval_seconds = parse_duration(every)
            if interval_seconds is None:
                every = click.prompt("Run every (e.g. 30m, 2h, 1d, 1w)", type=str)
                interval_seconds = parse_duration(every)
            payload["interval_seconds"] = interval_seconds
        elif schedule_type == "fixed":
            values = run_at_values
            if not values:
                raw = click.prompt(
                    "Run times (comma-separated ISO datetimes)",
                    type=str,
                )
                values = tuple(part.strip() for part in raw.split(",") if part.strip())
            payload["run_times"] = parse_run_times(values)
        else:
            if recurrence is None:
                recurrence = select_one(
                    "Recurrence",
                    [("weekly", "Weekly"), ("monthly", "Monthly")],
                    interactive=interactive,
                )
            if recurrence_day is None:
                if recurrence == "weekly":
                    recurrence_day = int(
                        select_one(
                            "Day of week",
                            [(str(i), day_name) for i, day_name in enumerate(WEEKDAY_NAMES)],
                            interactive=interactive,
                        )
                    )
                else:
                    recurrence_day = click.prompt("Day of month (1-31)", type=click.IntRange(1, 31))
            payload.update(
                {
                    "recurrence": recurrence,
                    "recurrence_day": recurrence_day,
                    "recurrence_hour": recurrence_hour,
                    "recurrence_minute": recurrence_minute,
                }
            )
    except ValueError as exc:
        click.echo(red("Invalid schedule configuration", "bold"))
        click.echo(white(str(exc), "normal"))
        return

    click.echo("")
    click.echo(white("Review", "normal"))
    click.echo(f"{green('Stack ID:', 'bold')} {stack_id}")
    click.echo(f"{green('Name:', 'bold')} {name}")
    click.echo(f"{green('Type:', 'bold')} {schedule_type}")
    click.echo(f"{green('Message:', 'bold')} {message}")
    if schedule_type == "interval":
        click.echo(f"{green('Every:', 'bold')} {format_duration(payload['interval_seconds'])}")
    elif schedule_type == "fixed":
        click.echo(f"{green('Run times:', 'bold')} {', '.join(payload['run_times'])}")
    else:
        click.echo(
            f"{green('Recurrence:', 'bold')} {payload['recurrence']} on "
            f"{format_recurrence_day(payload['recurrence'], payload['recurrence_day'])} "
            f"at {payload['recurrence_hour']:02d}:{payload['recurrence_minute']:02d} UTC"
        )
    click.echo(f"{green('Enabled:', 'bold')} {enabled}")
    click.echo(f"{green('Verbose:', 'bold')} {verbose}")
    click.echo("")

    if not yes and not click.confirm("Create this schedule?", default=True):
        click.echo(white("Cancelled.", "normal"))
        return

    response = client.post("/stack/schedule/create", json=payload)
    if response.status_code != 200:
        click.echo(red("Failed to create schedule", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return

    click.echo(green("Schedule created successfully", "bold"))
    click.echo(format_schedule(response.json()["schedule"]))


@schedule.command(name="update", help="Update a schedule")
@click.pass_context
@click.option("--id", "schedule_id", type=click.INT, help="Schedule ID")
@click.option("--name", type=click.STRING)
@click.option("--message", type=click.STRING)
@click.option("--every", type=click.STRING, help="Interval duration, e.g. 30m, 2h, 1d, 1w")
@click.option("--interval-seconds", type=click.INT, help="Interval in seconds (min 60)")
@click.option("--run-at", "run_at_values", multiple=True, help="Replace pending fixed run times")
@click.option("--recurrence", type=click.Choice(["weekly", "monthly"], case_sensitive=False))
@click.option("--recurrence-day", type=click.INT)
@click.option("--recurrence-hour", type=click.IntRange(0, 23))
@click.option("--recurrence-minute", type=click.IntRange(0, 59))
@click.option("--enabled/--disabled", default=None)
@click.option("--verbose/--no-verbose", default=None)
@click.option("--interactive/--no-interactive", default=True, help="Use interactive selection when ID is omitted")
def update_schedule(
    ctx: click.Context,
    schedule_id: int | None,
    name: str | None,
    message: str | None,
    every: str | None,
    interval_seconds: int | None,
    run_at_values: tuple[str, ...],
    recurrence: str | None,
    recurrence_day: int | None,
    recurrence_hour: int | None,
    recurrence_minute: int | None,
    enabled: bool | None,
    verbose: bool | None,
    interactive: bool,
):
    schedule_id = _select_schedule_id(ctx, schedule_id, interactive=interactive)
    if schedule_id is None:
        return

    client = ctx.obj["client"]
    payload: dict = {}

    if name is not None:
        payload["name"] = name
    if message is not None:
        payload["message"] = message
    if enabled is not None:
        payload["enabled"] = enabled
    if verbose is not None:
        payload["verbose"] = verbose
    if recurrence is not None:
        payload["recurrence"] = recurrence
    if recurrence_day is not None:
        payload["recurrence_day"] = recurrence_day
    if recurrence_hour is not None:
        payload["recurrence_hour"] = recurrence_hour
    if recurrence_minute is not None:
        payload["recurrence_minute"] = recurrence_minute

    try:
        if interval_seconds is not None:
            payload["interval_seconds"] = interval_seconds
        elif every is not None:
            payload["interval_seconds"] = parse_duration(every)
        if run_at_values:
            payload["run_times"] = parse_run_times(run_at_values)
    except ValueError as exc:
        click.echo(red("Invalid schedule configuration", "bold"))
        click.echo(white(str(exc), "normal"))
        return

    if not payload:
        click.echo(red("No updates provided", "bold"))
        return

    response = client.patch(f"/stack/schedule/{schedule_id}", json=payload)
    if response.status_code != 200:
        click.echo(red("Failed to update schedule", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return

    click.echo(green("Schedule updated successfully", "bold"))
    click.echo(format_schedule(response.json()["schedule"]))


@schedule.command(name="delete", help="Delete a schedule")
@click.pass_context
@click.option("--id", "schedule_id", type=click.INT, help="Schedule ID")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
@click.option("--interactive/--no-interactive", default=True, help="Use interactive selection when ID is omitted")
def delete_schedule(ctx: click.Context, schedule_id: int | None, yes: bool, interactive: bool):
    schedule_id = _select_schedule_id(ctx, schedule_id, interactive=interactive)
    if schedule_id is None:
        return

    client = ctx.obj["client"]

    if not yes and not click.confirm(f"Delete schedule {schedule_id}?", default=False):
        click.echo(white("Cancelled.", "normal"))
        return

    response = client.delete(f"/stack/schedule/{schedule_id}")
    if response.status_code != 200:
        click.echo(red("Failed to delete schedule", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return

    click.echo(green("Schedule deleted successfully", "bold"))


@schedule.command(name="runs", help="List runs for a schedule")
@click.pass_context
@click.option("--id", "schedule_id", type=click.INT, help="Schedule ID")
@click.option("--limit", type=click.IntRange(1, 100), default=20, show_default=True)
@click.option("--offset", type=click.IntRange(0), default=0, show_default=True)
@click.option("--interactive/--no-interactive", default=True, help="Use interactive selection when ID is omitted")
def list_schedule_runs(
    ctx: click.Context,
    schedule_id: int | None,
    limit: int,
    offset: int,
    interactive: bool,
):
    schedule_id = _select_schedule_id(ctx, schedule_id, interactive=interactive)
    if schedule_id is None:
        return

    client = ctx.obj["client"]
    response = client.get(
        f"/stack/schedule/{schedule_id}/runs",
        params={"limit": limit, "offset": offset},
    )
    if response.status_code != 200:
        click.echo(red("Failed to list schedule runs", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return

    runs = response.json().get("runs", [])
    if not runs:
        click.echo(red("No runs found for this schedule", "bold"))
        return

    for run in runs:
        click.echo(format_schedule_run(run))
        click.echo("")


@schedule.command(name="run", help="Get a scheduled run by run ID")
@click.pass_context
@click.option("--run-id", type=click.STRING, help="Scheduled run UUID")
@click.option("--id", "schedule_id", type=click.INT, help="Schedule ID (used when selecting a run interactively)")
@click.option("--interactive/--no-interactive", default=True, help="Use interactive selection when run ID is omitted")
def get_schedule_run(
    ctx: click.Context,
    run_id: str | None,
    schedule_id: int | None,
    interactive: bool,
):
    run_id = _select_schedule_run_id(
        ctx,
        schedule_id,
        run_id,
        interactive=interactive,
    )
    if run_id is None:
        return

    client = ctx.obj["client"]
    response = client.get(f"/stack/schedule/run/{run_id}")
    if response.status_code != 200:
        click.echo(red("Failed to get scheduled run", "bold"))
        click.echo(white(f"Error: {response.text}", "normal"))
        return

    run = response.json()["run"]
    click.echo(format_schedule_run(run))
    click.echo("")
    click.echo(green("Transcript", "bold"))
    messages_response = client.get(f"/stack/schedule/run/{run_id}/messages")
    if messages_response.status_code != 200:
        click.echo(red("Failed to load run messages", "bold"))
        click.echo(white(f"Error: {messages_response.text}", "normal"))
        return

    click.echo(format_run_messages(messages_response.json().get("messages", [])))