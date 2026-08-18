"""Multi-step Textual wizard for agent create / update."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Input,
    Label,
    Select,
    SelectionList,
    Static,
    TextArea,
)
from textual.widgets.selection_list import Selection

from lib.tools import (
    build_agent_tooling_preview,
    format_additional_tools,
    format_effective_tools,
    format_toolsets,
    prune_redundant_tool_ids,
    tool_choices_from_toolsets,
    tool_ids_from_toolsets,
)
from src.tui.theme import AGENT_WIZARD_CSS, PRIMARY, TEXT_MUTED

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

CUSTOM_ROLES = frozenset({"custom_supervisor", "custom_supporting_agent"})

Mode = Literal["create", "update"]


@dataclass
class AgentFormState:
    name: str = ""
    description: str = ""
    agent_type: str = "supporting"
    role: str = ""
    llm_id: int | None = None
    system_prompt: str = ""
    toolset_ids: list[int] = field(default_factory=list)
    tool_ids: list[int] = field(default_factory=list)


def _role_label(role: str) -> str:
    return role.replace("_", " ")


def _llm_label(llm: dict[str, Any]) -> str:
    return f"{llm['id']}: {llm['name']} ({llm['provider']})"


class AgentWizardApp(App[dict[str, Any] | None]):
    """Shared create/update wizard. Returns payload dict, or None if cancelled."""

    CSS = AGENT_WIZARD_CSS

    BINDINGS = [
        Binding("ctrl+n", "next", "Next", show=True),
        Binding("ctrl+b", "back", "Back", show=True),
        Binding("ctrl+s", "confirm", "Confirm", show=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(
        self,
        *,
        mode: Mode,
        llms: list[dict[str, Any]],
        toolsets: list[dict[str, Any]],
        initial: AgentFormState | None = None,
        baseline: AgentFormState | None = None,
        prebuilt_prompts: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._mode = mode
        self._llms = llms
        self._toolsets = toolsets
        self._state = initial or AgentFormState()
        self._baseline = baseline
        self._prebuilt_prompts = prebuilt_prompts or {}
        self._step_index = 0
        self._error = ""

    @property
    def _steps(self) -> list[str]:
        steps = ["details", "role_llm"]
        if self._state.agent_type != "supervisor":
            steps.append("tools")
        steps.extend(["prompt", "review"])
        return steps

    @property
    def _step(self) -> str:
        return self._steps[self._step_index]

    def compose(self) -> ComposeResult:
        with Vertical(id="wizard_container"):
            yield Static(self._header_title(), id="wizard_title")
            yield Static("", id="wizard_step")
            yield Static("", id="wizard_error")
            yield Vertical(id="step_body")
            with Horizontal(id="wizard_footer"):
                yield Static("", id="wizard_keymap")
                with Horizontal(id="wizard_buttons"):
                    yield Button("Cancel", id="btn_cancel")
                    yield Button("Back", id="btn_back")
                    yield Button("Next", id="btn_next")
                    yield Button("Confirm", id="btn_confirm")

    def on_mount(self) -> None:
        self.title = "astro"
        self._render_step()

    def _header_title(self) -> str:
        return "Create agent" if self._mode == "create" else "Update agent"

    def _set_error(self, message: str = "") -> None:
        self._error = message
        self.query_one("#wizard_error", Static).update(message)

    def _sync_buttons(self) -> None:
        at_start = self._step_index == 0
        at_end = self._step == "review"
        self.query_one("#btn_back", Button).disabled = at_start
        self.query_one("#btn_next", Button).display = not at_end
        self.query_one("#btn_confirm", Button).display = at_end
        keymap = "esc cancel · ctrl+b back · ctrl+n next"
        if at_end:
            keymap = "esc cancel · ctrl+b back · ctrl+s confirm"
        self.query_one("#wizard_keymap", Static).update(keymap)

    def _render_step(self) -> None:
        self._set_error()
        body = self.query_one("#step_body", Vertical)
        body.remove_children()
        step_label = f"Step {self._step_index + 1}/{len(self._steps)} — {self._step_title()}"
        self.query_one("#wizard_step", Static).update(step_label)
        self._sync_buttons()

        if self._step == "details":
            body.mount(*self._compose_details())
        elif self._step == "role_llm":
            body.mount(*self._compose_role_llm())
        elif self._step == "tools":
            body.mount(*self._compose_tools())
        elif self._step == "prompt":
            body.mount(*self._compose_prompt())
        else:
            body.mount(*self._compose_review())

        self.call_after_refresh(self._focus_step)

    def _step_title(self) -> str:
        return {
            "details": "Details",
            "role_llm": "Role & LLM",
            "tools": "Tools",
            "prompt": "System prompt",
            "review": "Review",
        }[self._step]

    def _focus_step(self) -> None:
        try:
            if self._step == "details":
                self.query_one("#name_input", Input).focus()
            elif self._step == "role_llm":
                self.query_one("#role_select", Select).focus()
            elif self._step == "tools":
                self.query_one("#toolset_list", SelectionList).focus()
            elif self._step == "prompt":
                self.query_one("#prompt_area", TextArea).focus()
            else:
                self.query_one("#btn_confirm", Button).focus()
        except Exception:
            pass

    def _apply_role_prompt(self, role: str) -> None:
        """Load the catalog prompt for a role (or clear for custom on create)."""
        if role in CUSTOM_ROLES:
            if self._mode == "create":
                self._state.system_prompt = ""
            return
        self._state.system_prompt = self._prebuilt_prompts.get(role, "")

    def _compose_details(self) -> list:
        widgets: list = [
            Label("Name", classes="field_label"),
            Input(self._state.name, placeholder="Agent name", id="name_input"),
            Label("Description", classes="field_label"),
            Input(
                self._state.description,
                placeholder="Short description",
                id="description_input",
            ),
            Label("Type", classes="field_label"),
        ]
        if self._mode == "update":
            widgets.append(
                Static(
                    f"{self._state.agent_type} (locked)",
                    classes="field_hint",
                    id="type_locked",
                )
            )
        else:
            widgets.append(
                Select(
                    [("Supporting", "supporting"), ("Supervisor", "supervisor")],
                    value=self._state.agent_type,
                    id="type_select",
                    allow_blank=False,
                )
            )
        return widgets

    def _compose_role_llm(self) -> list:
        roles = SUPERVISOR_ROLES if self._state.agent_type == "supervisor" else SUPPORTING_ROLES
        if self._state.role not in roles:
            self._state.role = roles[0]
            self._apply_role_prompt(self._state.role)
        elif (
            self._mode == "create"
            and not self._state.system_prompt.strip()
            and self._state.role not in CUSTOM_ROLES
        ):
            self._apply_role_prompt(self._state.role)
        role_options = [(_role_label(role), role) for role in roles]

        llm_options: list[tuple[str, int]] = [(_llm_label(llm), llm["id"]) for llm in self._llms]
        llm_value: int | Select.BLANK = Select.BLANK
        if self._state.llm_id is not None and any(
            llm["id"] == self._state.llm_id for llm in self._llms
        ):
            llm_value = self._state.llm_id
        elif llm_options:
            llm_value = llm_options[0][1]
            self._state.llm_id = llm_value

        return [
            Label("Role", classes="field_label"),
            Select(role_options, value=self._state.role, id="role_select", allow_blank=False),
            Label("LLM", classes="field_label"),
            Select(llm_options, value=llm_value, id="llm_select", allow_blank=False),
        ]

    def _compose_tools(self) -> list:
        toolset_selections = [
            Selection(
                f"{ts['id']}: {ts['name']} ({ts.get('type', '?')}, {len(ts.get('tools') or [])} tools)",
                ts["id"],
                initial_state=ts["id"] in self._state.toolset_ids,
            )
            for ts in self._toolsets
        ]
        covered = tool_ids_from_toolsets(self._toolsets, self._state.toolset_ids)
        tool_choices = tool_choices_from_toolsets(self._toolsets, exclude_ids=covered)
        tool_selections = [
            Selection(
                f"{tool_id}: {label}",
                tool_id,
                initial_state=tool_id in self._state.tool_ids,
            )
            for tool_id, label in tool_choices
        ]

        widgets: list = [
            Label("Toolsets", classes="field_label"),
            Static("Space to toggle · Enter to activate", classes="field_hint"),
            SelectionList(*toolset_selections, id="toolset_list"),
            Label("Additional tools", classes="field_label"),
            Static(
                "Tools already covered by selected toolsets are omitted.",
                classes="field_hint",
            ),
        ]
        if tool_selections:
            widgets.append(SelectionList(*tool_selections, id="tool_list"))
        else:
            widgets.append(Static("(none available)", classes="field_hint", id="tool_list_empty"))
        return widgets

    def _compose_prompt(self) -> list:
        if self._state.role in CUSTOM_ROLES:
            hint = "Custom roles require a system prompt."
        else:
            hint = "Prebuilt prompt loaded — tweak as needed, or leave as-is."
        return [
            Label("System prompt", classes="field_label"),
            Static(hint, classes="field_hint"),
            TextArea(self._state.system_prompt, id="prompt_area", show_line_numbers=True),
        ]

    def _compose_review(self) -> list:
        text = Text()
        text.append("Name  ", style=f"bold {PRIMARY}")
        text.append(f"{self._state.name}\n")
        text.append("About ", style=f"bold {PRIMARY}")
        text.append(f"{self._state.description}\n")
        text.append("Type  ", style=f"bold {PRIMARY}")
        text.append(f"{self._state.agent_type}\n")
        text.append("Role  ", style=f"bold {PRIMARY}")
        text.append(f"{self._state.role}\n")
        text.append("LLM   ", style=f"bold {PRIMARY}")
        text.append(f"{self._state.llm_id}\n")

        prompt_preview = self._state.system_prompt.strip()
        if not prompt_preview:
            prompt_preview = "(empty)"
        elif len(prompt_preview) > 240:
            prompt_preview = prompt_preview[:237] + "..."
        text.append("Prompt\n", style=f"bold {PRIMARY}")
        text.append(f"{prompt_preview}\n\n", style=TEXT_MUTED)

        if self._state.agent_type == "supervisor":
            text.append("Tools ", style=f"bold {PRIMARY}")
            text.append("(none — supervisors coordinate supporting agents)\n")
        else:
            pruned, _ = prune_redundant_tool_ids(
                self._toolsets,
                self._state.toolset_ids,
                self._state.tool_ids,
            )
            preview = build_agent_tooling_preview(
                self._toolsets,
                self._state.toolset_ids,
                pruned,
            )
            text.append("Toolsets\n", style=f"bold {PRIMARY}")
            text.append(f"{format_toolsets(preview['toolsets'])}\n", style=TEXT_MUTED)
            text.append("Additional\n", style=f"bold {PRIMARY}")
            text.append(f"{format_additional_tools(preview)}\n", style=TEXT_MUTED)
            text.append("Effective\n", style=f"bold {PRIMARY}")
            text.append(f"{format_effective_tools(preview)}\n", style=TEXT_MUTED)

        return [
            VerticalScroll(Static(text, id="review_content"), id="review_panel"),
        ]

    def _capture_step(self, *, validate: bool = True) -> bool:
        """Persist current step widgets into state. Return False if invalid."""
        if self._step == "details":
            name = self.query_one("#name_input", Input).value.strip()
            description = self.query_one("#description_input", Input).value.strip()
            if validate and not name:
                self._set_error("Name is required.")
                return False
            if validate and not description:
                self._set_error("Description is required.")
                return False
            self._state.name = name
            self._state.description = description
            if self._mode == "create":
                selected = self.query_one("#type_select", Select).value
                if validate and selected is Select.BLANK:
                    self._set_error("Type is required.")
                    return False
                if selected is not Select.BLANK:
                    new_type = str(selected)
                    if new_type != self._state.agent_type:
                        self._state.agent_type = new_type
                        roles = (
                            SUPERVISOR_ROLES
                            if new_type == "supervisor"
                            else SUPPORTING_ROLES
                        )
                        if self._state.role not in roles:
                            self._state.role = roles[0]
                            self._apply_role_prompt(self._state.role)
                        if new_type == "supervisor":
                            self._state.toolset_ids = []
                            self._state.tool_ids = []
            return True

        if self._step == "role_llm":
            role = self.query_one("#role_select", Select).value
            llm = self.query_one("#llm_select", Select).value
            if validate and role is Select.BLANK:
                self._set_error("Role is required.")
                return False
            if validate and llm is Select.BLANK:
                self._set_error("LLM is required.")
                return False
            if role is not Select.BLANK:
                new_role = str(role)
                if new_role != self._state.role:
                    self._state.role = new_role
                    self._apply_role_prompt(new_role)
            if llm is not Select.BLANK:
                self._state.llm_id = int(llm)
            return True

        if self._step == "tools":
            toolsets = list(self.query_one("#toolset_list", SelectionList).selected)
            self._state.toolset_ids = [int(item) for item in toolsets]
            try:
                tools = list(self.query_one("#tool_list", SelectionList).selected)
                self._state.tool_ids = [int(item) for item in tools]
            except Exception:
                self._state.tool_ids = [
                    tool_id
                    for tool_id in self._state.tool_ids
                    if tool_id
                    not in tool_ids_from_toolsets(self._toolsets, self._state.toolset_ids)
                ]
            self._state.tool_ids, _ = prune_redundant_tool_ids(
                self._toolsets,
                self._state.toolset_ids,
                self._state.tool_ids,
            )
            return True

        if self._step == "prompt":
            prompt = str(self.query_one("#prompt_area", TextArea).text)
            if (
                validate
                and self._state.role in CUSTOM_ROLES
                and not prompt.strip()
            ):
                self._set_error("System prompt is required for custom roles.")
                return False
            self._state.system_prompt = prompt
            return True

        return True

    def _build_create_payload(self) -> dict[str, Any]:
        prompt = self._state.system_prompt.strip()
        if self._state.role in CUSTOM_ROLES:
            prompt_value: str | None = prompt
        else:
            # Send tweaked (or stock) prebuilt text; fall back to server fill if empty.
            prompt_value = prompt or None

        if self._state.agent_type == "supervisor":
            toolset_ids = None
            tool_ids = None
        else:
            toolset_ids = list(self._state.toolset_ids)
            tool_ids = list(self._state.tool_ids)

        return {
            "name": self._state.name,
            "description": self._state.description,
            "system_prompt": prompt_value,
            "llm": self._state.llm_id,
            "type": self._state.agent_type,
            "role": self._state.role,
            "toolset_ids": toolset_ids,
            "tool_ids": tool_ids,
        }

    def _build_update_payload(self) -> dict[str, Any]:
        assert self._baseline is not None
        updates: dict[str, Any] = {}
        if self._state.name != self._baseline.name:
            updates["name"] = self._state.name
        if self._state.description != self._baseline.description:
            updates["description"] = self._state.description
        if self._state.role != self._baseline.role:
            updates["role"] = self._state.role
        if self._state.llm_id != self._baseline.llm_id:
            updates["llm"] = self._state.llm_id
        if self._state.system_prompt != self._baseline.system_prompt:
            updates["system_prompt"] = self._state.system_prompt
        if self._state.agent_type != "supervisor":
            if list(self._state.toolset_ids) != list(self._baseline.toolset_ids):
                updates["toolset_ids"] = list(self._state.toolset_ids)
            if list(self._state.tool_ids) != list(self._baseline.tool_ids):
                updates["tool_ids"] = list(self._state.tool_ids)
        return updates

    def action_next(self) -> None:
        if self._step == "review":
            return
        if not self._capture_step(validate=True):
            return
        if self._step_index >= len(self._steps) - 1:
            return
        self._step_index += 1
        if self._step_index >= len(self._steps):
            self._step_index = len(self._steps) - 1
        self._render_step()

    def action_back(self) -> None:
        if self._step_index == 0:
            return
        self._capture_step(validate=False)
        self._step_index -= 1
        self._render_step()

    def action_cancel(self) -> None:
        self.exit(None)

    def action_confirm(self) -> None:
        if self._step != "review":
            if self._step == "prompt" and self._capture_step(validate=True):
                self.action_next()
            return
        if self._mode == "create":
            self.exit(self._build_create_payload())
            return
        updates = self._build_update_payload()
        self.exit(updates)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn_cancel":
            self.action_cancel()
        elif button_id == "btn_back":
            self.action_back()
        elif button_id == "btn_next":
            self.action_next()
        elif button_id == "btn_confirm":
            self.action_confirm()


def _state_from_initial(initial: dict[str, Any] | None) -> AgentFormState:
    if not initial:
        return AgentFormState()
    return AgentFormState(
        name=str(initial.get("name") or ""),
        description=str(initial.get("description") or ""),
        agent_type=str(initial.get("agent_type") or initial.get("type") or "supporting"),
        role=str(initial.get("role") or ""),
        llm_id=initial.get("llm_id"),
        system_prompt=str(initial.get("system_prompt") or ""),
        toolset_ids=list(initial.get("toolset_ids") or []),
        tool_ids=list(initial.get("tool_ids") or []),
    )


def run_agent_wizard(
    *,
    mode: Mode,
    llms: list[dict[str, Any]],
    toolsets: list[dict[str, Any]],
    initial: dict[str, Any] | None = None,
    baseline: dict[str, Any] | None = None,
    prebuilt_prompts: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Launch the wizard. Returns create payload, update diff, or None if cancelled."""
    catalog = prebuilt_prompts or {}
    state = _state_from_initial(initial)
    if (
        mode == "create"
        and not state.system_prompt.strip()
        and state.role
        and state.role not in CUSTOM_ROLES
    ):
        state.system_prompt = catalog.get(state.role, "")
    baseline_state = None
    if mode == "update":
        baseline_state = _state_from_initial(baseline if baseline is not None else initial)
    app = AgentWizardApp(
        mode=mode,
        llms=llms,
        toolsets=toolsets,
        initial=state,
        baseline=baseline_state,
        prebuilt_prompts=catalog,
    )
    return app.run()
