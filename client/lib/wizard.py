import click
from InquirerPy import inquirer
from InquirerPy.base.control import Choice

def _parse_csv_ids(value: str) -> list[int]:
    raw = [part.strip() for part in value.split(",") if part.strip()]
    ids: list[int] = []
    for part in raw:
        try:
            ids.append(int(part))
        except ValueError as exc:
            raise click.BadParameter(f"Invalid ID '{part}'. Use comma-separated integer IDs.") from exc
    return ids


def _is_interactive(interactive: bool) -> bool:
    return interactive and inquirer is not None and click.get_text_stream("stdin").isatty()


def select_one(message: str, choices: list[tuple[str, str]], interactive: bool) -> str:
    if _is_interactive(interactive):
        prompt_choices = [Choice(value=value, name=label) for value, label in choices]
        result = inquirer.select(message=message, choices=prompt_choices).execute()
        return str(result)

    click.echo(message)
    for value, label in choices:
        click.echo(f"  - {value}: {label}")
    valid = [value for value, _ in choices]
    return click.prompt("Enter value", type=click.Choice(valid, case_sensitive=False))


def select_many_ids(message: str, choices: list[tuple[int, str]], interactive: bool) -> list[int]:
    if not choices:
        return []

    if _is_interactive(interactive):
        prompt_choices = [Choice(value=item_id, name=f"{item_id}: {label}") for item_id, label in choices]
        selected = inquirer.checkbox(
            message=message,
            choices=prompt_choices,
            instruction="Space to toggle, Enter to continue",
        ).execute()
        return [int(item) for item in selected]

    click.echo(message)
    for item_id, label in choices:
        click.echo(f"  - {item_id}: {label}")
    raw = click.prompt("IDs (comma-separated, leave empty for none)", default="", show_default=False)
    return _parse_csv_ids(raw)