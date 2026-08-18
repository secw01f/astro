"""Multiline system-prompt editor TUI."""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static, TextArea

from src.tui.theme import PROMPT_EDITOR_CSS


class PromptEditorApp(App[str | None]):
    """Full-screen multiline editor. Returns text on save, None on cancel."""

    CSS = PROMPT_EDITOR_CSS

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(
        self,
        *,
        title: str = "Edit system prompt",
        subtitle: str = "Ctrl+S save · Esc cancel",
        initial: str = "",
    ) -> None:
        super().__init__()
        self._title = title
        self._subtitle = subtitle
        self._initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="editor_container"):
            yield Static(self._title, id="editor_title")
            yield Static(self._subtitle, id="editor_subtitle")
            yield TextArea(
                self._initial,
                id="editor_body",
                show_line_numbers=True,
            )
            yield Static("ctrl+s save · esc cancel", id="editor_status")
            with Horizontal(id="editor_buttons"):
                yield Button("Save", id="save_prompt")
                yield Button("Cancel", id="cancel_prompt")

    def on_mount(self) -> None:
        self.title = "astro"
        self.query_one("#editor_body", TextArea).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save_prompt":
            self.action_save()
        else:
            self.action_cancel()

    def action_save(self) -> None:
        text = str(self.query_one("#editor_body", TextArea).text)
        self.exit(text)

    def action_cancel(self) -> None:
        self.exit(None)


def edit_multiline_prompt(
    *,
    title: str = "Edit system prompt",
    subtitle: str = "Edit the prompt below, then save.",
    initial: str = "",
) -> str | None:
    """Run the prompt editor and return the result, or None if cancelled."""
    return PromptEditorApp(
        title=title,
        subtitle=subtitle,
        initial=initial,
    ).run()
