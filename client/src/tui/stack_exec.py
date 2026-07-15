import json
import os

import httpx
from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, TextArea

from src.tui.theme import (
    ACCENT,
    AGENT_COLORS,
    DANGER,
    INFO,
    PRIMARY,
    STACK_EXEC_CSS,
    SUCCESS,
    TEXT_DIM,
    TEXT_MUTED,
)

_SUPERVISOR_STYLE = f"bold {INFO}"

_CHAT_COMMANDS = {
    "/exit": "Quit",
    "/clear": "Clear transcript",
    "/help": "Show commands",
    "/info": "Stack details",
    "/history": "Recent messages",
}


def _format_user_message(username: str, content: str) -> Text:
    text = Text()
    text.append("› ", style=ACCENT)
    text.append(f"{username}:", style="bold")
    text.append("\n")
    text.append(content)
    return text


def _format_assistant_header(name: str, *, style: str) -> Text:
    text = Text()
    text.append(name, style=style)
    text.append("\n")
    return text


def _needs_sentence_space(last_char: str | None, chunk: str) -> bool:
    if not last_char or not chunk:
        return False
    if chunk[0].isspace() or chunk[0] in ".,!?;:)]}\"'":
        return False
    return last_char in ".!?"


class MessageTextArea(TextArea):
    """Multiline prompt: Enter sends, Shift+Enter / Ctrl+J insert a newline."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._app: StackExecApp | None = None

    def set_app(self, app: "StackExecApp") -> None:
        self._app = app

    def on_mount(self) -> None:
        self.show_vertical_scrollbar = False
        self.show_horizontal_scrollbar = False
        self._update_height()

    def _on_key(self, event: events.Key) -> None:
        # Many terminals (macOS Terminal.app, VS Code, tmux, ...) send the same
        # byte for Enter and Shift+Enter, so "shift+enter" never reaches us.
        # Ctrl+J sends LF (0x0A), distinct from Enter's CR (0x0D), and works
        # everywhere as a newline fallback.
        if event.key in ("shift+enter", "ctrl+j"):
            self.insert("\n")
            event.prevent_default()
            return

        if event.key == "enter" and self._app is not None:
            message = str(self.text).strip()
            if message:
                self.text = ""
                self._app.submit_message(message)
                event.prevent_default()
                return

        super()._on_key(event)

    @on(TextArea.Changed)
    def _update_height(self, _event: TextArea.Changed | None = None) -> None:
        if not self.parent:
            return

        line_count = self.document.line_count
        target_lines = min(max(1, line_count), 8)
        new_height = target_lines + 2

        if self.parent.styles.height != new_height:
            self.parent.styles.height = new_height
            self.scroll_cursor_visible()


class FileRequestScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "skip", "Skip")]

    def __init__(self, description: str, request_id: str) -> None:
        super().__init__()
        self._description = description
        self._request_id = request_id

    def compose(self) -> ComposeResult:
        with Vertical(id="file-dialog"):
            yield Label("File requested by agent", classes="file-title")
            yield Static(self._description or "Please provide a file.")
            yield Label(f"Request ID: {self._request_id}", classes="file-meta")
            yield Input(placeholder="Path to file", id="file-path")
            with Horizontal(id="file-buttons"):
                yield Button("Upload", id="upload")
                yield Button("Skip", id="skip")

    def on_mount(self) -> None:
        self.query_one("#file-path", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "upload":
            self._submit()
        else:
            self.dismiss(None)

    def action_skip(self) -> None:
        self.dismiss(None)

    def _submit(self) -> None:
        path = self.query_one("#file-path", Input).value.strip()
        self.dismiss(path or None)


class StackExecApp(App):
    """Textual TUI for `astro stack exec`."""

    CSS = STACK_EXEC_CSS

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("f1", "show_help", "Help"),
    ]

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None,
        stack_id: int,
        stack_name: str,
        stack_description: str = "",
        supervisor_name: str = "",
        supporting_names: list[str] | None = None,
        username: str,
        verbose: bool = False,
    ) -> None:
        super().__init__()
        self._base_url = base_url
        self._token = token
        self._stack_id = stack_id
        self._stack_name = stack_name
        self._stack_description = stack_description
        self._supervisor_name = supervisor_name or stack_name
        self._supporting_names = supporting_names or []
        self._username = username
        self._verbose = verbose
        self._client: httpx.AsyncClient | None = None
        self._run_id: str | None = None
        self._agent_styles: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="main_container"):
            with Horizontal(id="content_container"):
                with Vertical(id="chat_area_container"):
                    yield VerticalScroll(id="chat_history")
                    with Horizontal(id="status_bar"):
                        yield Static(id="status_text")
                        yield Static(id="keymap_indicator")
                    with Horizontal(id="prompt_container"):
                        yield Static("> ", id="prompt_prefix")
                        yield MessageTextArea(
                            "",
                            id="prompt",
                            show_line_numbers=False,
                        )
                with Vertical(id="sidebar"):
                    yield Static("Info", id="sidebar-title")
                    yield Static(id="sidebar-panel")

    def on_mount(self) -> None:
        headers = {"X-API-KEY": self._token} if self._token else {}
        self._client = httpx.AsyncClient(base_url=self._base_url, headers=headers)
        self.title = "astro"

        self._render_sidebar()
        self._update_status("Ready")
        self.query_one("#keymap_indicator", Static).update(self._keymap_text())
        self._show_empty_state()
        prompt = self.query_one("#prompt", MessageTextArea)
        prompt.set_app(self)
        prompt.focus()

        if self._verbose:
            self._system(
                "Verbose mode: supervisor streams live; supporting agents appear when complete."
            )

    async def on_unmount(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    @property
    def _transcript(self) -> VerticalScroll:
        return self.query_one("#chat_history", VerticalScroll)

    def _keymap_text(self) -> str:
        return "enter send · shift+enter/ctrl+j newline · F1 help · ctrl+c quit"

    def _update_status(self, message: str) -> None:
        self.query_one("#status_text", Static).update(message)

    def _render_sidebar(self) -> None:
        panel = Text()
        panel.append("Stack\n", style=f"bold {PRIMARY}")
        panel.append("Name  ", style=TEXT_MUTED)
        panel.append(f"{self._stack_name}\n", style=f"bold {TEXT_DIM}")
        panel.append("ID    ", style=TEXT_MUTED)
        panel.append(f"{self._stack_id}\n", style=TEXT_DIM)
        if self._stack_description:
            panel.append("About ", style=TEXT_MUTED)
            panel.append(f"{self._stack_description}\n", style=TEXT_DIM)
        panel.append("User  ", style=TEXT_MUTED)
        panel.append(f"{self._username}@astro\n", style=TEXT_DIM)
        panel.append("Mode  ", style=TEXT_MUTED)
        panel.append(
            ("verbose\n" if self._verbose else "standard\n"),
            style=TEXT_DIM,
        )

        panel.append("\nAgents\n", style=f"bold {PRIMARY}")
        panel.append("Supervisor\n", style=TEXT_MUTED)
        panel.append(f"  {self._supervisor_name}\n", style=f"bold {TEXT_DIM}")
        panel.append("Supporting\n", style=TEXT_MUTED)
        if self._supporting_names:
            for name in self._supporting_names:
                panel.append(f"  {name}\n", style=TEXT_DIM)
        else:
            panel.append("  (none)\n", style=TEXT_MUTED)

        self.query_one("#sidebar-panel", Static).update(panel)

    def _show_empty_state(self) -> None:
        if self._transcript.children:
            return
        placeholder = Static(
            "Send a message to start the stack run.",
            id="empty-state",
            classes="chat-content",
        )
        self._transcript.mount(placeholder)

    def _hide_empty_state(self) -> None:
        try:
            empty = self._transcript.query_one("#empty-state")
            empty.remove()
        except Exception:
            pass

    def _style_for(self, agent: str) -> str:
        if agent == self._supervisor_name:
            return _SUPERVISOR_STYLE
        if agent not in self._agent_styles:
            color = AGENT_COLORS[len(self._agent_styles) % len(AGENT_COLORS)]
            self._agent_styles[agent] = f"bold {color}"
        return self._agent_styles[agent]

    def _post(self, renderable, *, kind: str = "system") -> None:
        self._hide_empty_state()
        static = Static(renderable, classes=f"message message-{kind} chat-content")
        self._transcript.mount(static)
        self._transcript.scroll_end(animate=False)

    async def _mount(self, renderable, *, kind: str = "assistant") -> Static:
        self._hide_empty_state()
        static = Static(renderable, classes=f"message message-{kind} chat-content")
        await self._transcript.mount(static)
        self._transcript.scroll_end(animate=False)
        return static

    def _system(self, text: str) -> None:
        self._post(Text(text, style=TEXT_MUTED), kind="system")

    def _error(self, text: str) -> None:
        self._post(Text(text, style=f"bold {DANGER}"), kind="error")

    def _success(self, text: str) -> None:
        self._post(Text(text, style=f"bold {SUCCESS}"), kind="success")

    def action_show_help(self) -> None:
        self.run_worker(self._handle_command("/help"))

    def submit_message(self, raw: str) -> None:
        self.run_worker(self._handle_submitted_message(raw))

    async def _handle_submitted_message(self, raw: str) -> None:
        if not raw:
            return

        cmd = raw.strip().lower()
        if "\n" not in raw and cmd in _CHAT_COMMANDS:
            await self._handle_command(cmd)
            return

        self._post(_format_user_message(self._username, raw), kind="user")
        self.stream_message(raw)

    async def _handle_command(self, cmd: str) -> None:
        if cmd == "/exit":
            self.exit()
        elif cmd == "/clear":
            await self._transcript.remove_children()
            self._show_empty_state()
        elif cmd == "/help":
            help_text = Text()
            help_text.append("Commands\n", style=f"bold {PRIMARY}")
            for command, description in _CHAT_COMMANDS.items():
                help_text.append(f"  {command:<10}", style=f"bold {SUCCESS}")
                help_text.append(f"{description}\n")
            self._post(help_text, kind="system")
        elif cmd == "/info":
            await self._show_info()
        elif cmd == "/history":
            await self._show_history()

    async def _show_info(self) -> None:
        response = await self._client.get(f"/stack/{self._stack_id}")
        if response.status_code != 200:
            self._error("Failed to get stack info")
            self._error(f"Error: {response.text}")
            return
        stack = response.json()["stack"]
        block = Text()
        block.append(f"{self._stack_name}\n", style=f"bold {PRIMARY}")
        if self._stack_description:
            block.append(f"{self._stack_description}\n\n", style=TEXT_MUTED)
        rows = [
            ("Supervisor", self._supervisor_name),
            ("Supporting", ", ".join(self._supporting_names) or "(none)"),
            ("Created", str(stack.get("created", "?"))),
        ]
        for label, value in rows:
            block.append(f"{label}: ", style=f"bold {INFO}")
            block.append(f"{value}\n")
        self._post(block, kind="system")

    async def _show_history(self) -> None:
        response = await self._client.post(
            "/message/history",
            json={"stack_id": self._stack_id, "limit": 10, "offset": 0},
        )
        if response.status_code != 200:
            self._error("Failed to get message history")
            self._error(f"Error: {response.text}")
            return
        messages = response.json()["messages"]
        if not messages:
            self._system("(no history)")
            return
        self._post(Text("Recent history\n", style=f"bold {PRIMARY}"), kind="system")
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            if role == "assistant":
                block = _format_assistant_header(self._supervisor_name, style=_SUPERVISOR_STYLE)
                block.append(content)
                self._post(block, kind="assistant")
            elif role == "user":
                self._post(_format_user_message(self._username, content), kind="user")
            else:
                block = Text()
                block.append(f"{str(role).capitalize()}\n", style="bold")
                block.append(content)
                self._post(block, kind="system")

    @work(exclusive=True)
    async def stream_message(self, message: str) -> None:
        prompt = self.query_one("#prompt", MessageTextArea)
        prompt.disabled = True
        self._update_status("Running")
        try:
            await self._stream(message)
        finally:
            self._update_status("Ready")
            prompt.disabled = False
            prompt.focus()

    async def _stream(self, message: str) -> None:
        client = self._client
        name = self._supervisor_name
        stream_timeout = httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0)
        payload = {"message": message, "verbose": self._verbose}

        supporting_buffers: dict[str, str] = {}
        supporting_order: list[str] = []
        last_token_agent: str | None = None
        last_rendered_char: str | None = None
        supervisor_line: Static | None = None
        supervisor_text: Text | None = None

        async def flush_supporting(agent_name: str | None = None) -> None:
            targets = [agent_name] if agent_name is not None else list(supporting_order)
            for target in targets:
                if target not in supporting_buffers:
                    continue
                text = supporting_buffers.pop(target, "").strip()
                if target in supporting_order:
                    supporting_order.remove(target)
                block = _format_assistant_header(target, style=self._style_for(target))
                if text:
                    block.append(text)
                await self._mount(block, kind="assistant")

        try:
            async with client.stream(
                "POST",
                f"/stack/{self._stack_id}/exec",
                json=payload,
                timeout=stream_timeout,
            ) as response:
                if response.status_code != 200:
                    await response.aread()
                    self._error("Failed to execute stack")
                    self._error(f"Error: {response.text}")
                    return

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue

                    try:
                        data = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

                    typ = data.get("type")
                    if self._run_id is None and data.get("run_id"):
                        self._run_id = data["run_id"]

                    if typ == "token":
                        ag = data.get("agent")
                        content = data.get("content") or ""

                        if self._verbose and isinstance(ag, str) and ag != name:
                            supporting_buffers.setdefault(ag, "")
                            if ag not in supporting_order:
                                supporting_order.append(ag)
                            supporting_buffers[ag] += content
                            last_token_agent = ag
                            continue

                        if self._verbose and last_token_agent != name:
                            await flush_supporting()
                            supervisor_line = None
                            supervisor_text = None
                            last_rendered_char = None
                            last_token_agent = name

                        if supervisor_line is None:
                            supervisor_text = _format_assistant_header(
                                name, style=_SUPERVISOR_STYLE
                            )
                            supervisor_line = await self._mount(supervisor_text, kind="assistant")

                        if _needs_sentence_space(last_rendered_char, content):
                            content = " " + content
                        supervisor_text.append(content)
                        supervisor_line.update(supervisor_text)
                        self._transcript.scroll_end(animate=False)
                        if content:
                            last_rendered_char = content[-1]
                    elif typ == "tool_result":
                        if self._verbose:
                            tool_name = data.get("tool_name")
                            if isinstance(tool_name, str) and tool_name in supporting_buffers:
                                await flush_supporting(tool_name)
                    elif typ == "file_request":
                        request_id = data.get("request_id")
                        event_run_id = data.get("run_id") or self._run_id
                        if not request_id or not event_run_id:
                            self._error("Invalid file_request event (missing ids)")
                            continue
                        self._update_status("Waiting for file")
                        await self._handle_file_request(
                            event_run_id,
                            request_id,
                            data.get("description") or "",
                        )
                        self._update_status("Running")
                        supervisor_line = None
                        supervisor_text = None
                        last_rendered_char = None
                    elif typ == "end":
                        break
                    elif typ == "error":
                        if self._verbose:
                            await flush_supporting()
                        self._error(data.get("content") or "Unknown error")
                        break

                if self._verbose:
                    await flush_supporting()
        except httpx.ConnectError:
            self._error("Failed to connect to the API")
        except httpx.ReadTimeout:
            self._error("Read timed out waiting for the API (response too slow).")

    async def _handle_file_request(self, run_id: str, request_id: str, description: str) -> None:
        path = await self.push_screen_wait(FileRequestScreen(description, request_id))
        if not path:
            self._system("File request skipped.")
            return
        await self._upload_file(run_id, request_id, path)

    async def _upload_file(self, run_id: str, request_id: str, path: str) -> None:
        filename = os.path.basename(path)
        try:
            with open(path, "rb") as handle:
                response = await self._client.post(
                    f"/stack/{self._stack_id}/run/{run_id}/file",
                    data={"request_id": request_id},
                    files={"file": (filename, handle)},
                )
        except OSError as exc:
            self._error(f"Could not read file: {exc}")
            return

        if response.status_code != 200:
            self._error("Failed to upload file")
            self._error(f"Error: {response.text}")
            return

        payload = response.json()
        self._success(
            f"Uploaded {payload.get('filename', filename)} "
            f"(file_id={payload.get('file_id')})"
        )
