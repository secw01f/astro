"""Theme tokens for the ASTRO TUI.

Palette from secw01f-ui `astroColorScheme`; layout patterns from Strix TUI.
"""

PRIMARY = "#1d7fea"
ACCENT = "#559af1"
SUCCESS = "#7dff95"
WARNING = "#ffbc5e"
DANGER = "#ff8080"
INFO = "#87d1ff"

# Strix-inspired neutrals
BG = "#000000"
TEXT = "#d4d4d4"
TEXT_DIM = "#a3a3a3"
TEXT_MUTED = "#737373"
BORDER = "#333333"
BORDER_SUBTLE = "#1a1a1a"
PANEL_BG = "#0a0a0a"

AGENT_COLORS = (
    PRIMARY,
    ACCENT,
    SUCCESS,
    INFO,
    WARNING,
    "#722ed1",
    DANGER,
)

STACK_EXEC_CSS = f"""
Screen {{
    background: {BG};
    color: {TEXT};
}}

#main_container {{
    height: 100%;
    padding: 0;
    background: {BG};
}}

#content_container {{
    height: 1fr;
    padding: 0 0 0 1;
    background: transparent;
}}

#chat_area_container {{
    width: 1fr;
    background: transparent;
}}

#sidebar {{
    width: 30;
    background: transparent;
    border-left: round {BORDER};
    padding: 1;
}}

#sidebar-title {{
    color: {TEXT_DIM};
    text-style: bold;
    margin-bottom: 1;
}}

#sidebar-panel {{
    height: 1fr;
    background: transparent;
    color: {TEXT};
}}

#chat_history {{
    height: 1fr;
    background: transparent;
    border: round {BORDER_SUBTLE};
    padding: 0;
    margin-bottom: 0;
    scrollbar-background: {BG};
    scrollbar-color: {BORDER_SUBTLE};
    scrollbar-corner-color: {BG};
    scrollbar-size: 1 1;
}}

#empty-state {{
    height: 100%;
    content-align: center middle;
    text-align: center;
    color: {TEXT_MUTED};
    text-style: italic;
    background: transparent;
}}

#status_bar {{
    height: 1;
    background: transparent;
    padding: 0 1;
    margin: 0;
}}

#status_text {{
    width: 1fr;
    height: 100%;
    background: transparent;
    color: {TEXT_DIM};
    content-align: left middle;
}}

#keymap_indicator {{
    width: auto;
    height: 100%;
    background: transparent;
    color: {TEXT_MUTED};
    content-align: right middle;
}}

#prompt_container {{
    height: 3;
    min-height: 3;
    background: transparent;
    border: round {BORDER};
    margin: 0;
    padding: 0;
    layout: horizontal;
    align-vertical: top;
}}

#prompt_container:focus-within {{
    border: round {PRIMARY};
}}

#prompt_container:focus-within #prompt_prefix {{
    color: {PRIMARY};
    text-style: bold;
}}

#prompt_prefix {{
    width: auto;
    height: 100%;
    padding: 0 0 0 1;
    color: {TEXT_MUTED};
    content-align-vertical: top;
}}

#prompt {{
    width: 1fr;
    height: 100%;
    background: transparent;
    border: none;
    color: {TEXT};
    padding: 0;
    margin: 0;
}}

#prompt:focus {{
    border: none;
}}

#prompt .text-area--cursor-line {{
    background: transparent;
}}

#prompt:focus .text-area--cursor-line {{
    background: transparent;
}}

#prompt > .text-area--cursor {{
    color: {PRIMARY};
    background: {PRIMARY};
}}

.chat-content {{
    margin: 0;
    padding: 0 1;
    background: transparent;
    width: 100%;
}}

.message {{
    height: auto;
    margin: 0;
    padding: 0;
    background: transparent;
    width: 100%;
}}

.message-user {{
    color: {TEXT};
    margin-bottom: 1;
    padding: 0 1;
}}

.message-assistant {{
    color: {TEXT};
    margin-bottom: 1;
    padding: 0 1;
}}

.message-system {{
    color: {TEXT_MUTED};
    margin-bottom: 1;
    padding: 0 1;
}}

.message-error {{
    color: {DANGER};
    text-style: bold;
    margin-bottom: 1;
    padding: 0 1;
}}

.message-success {{
    color: {SUCCESS};
    margin-bottom: 1;
    padding: 0 1;
}}

FileRequestScreen {{
    align: center middle;
    background: {BG} 80%;
}}

#file-dialog {{
    width: 72;
    height: auto;
    padding: 1 2;
    border: round {BORDER};
    background: {PANEL_BG};
}}

#file-dialog .file-title {{
    text-style: bold;
    color: {WARNING};
    margin-bottom: 1;
}}

#file-dialog .file-meta {{
    color: {TEXT_MUTED};
    margin-bottom: 1;
}}

#file-buttons {{
    height: auto;
    align: right middle;
    margin-top: 1;
    border-top: solid {BORDER_SUBTLE};
    padding-top: 1;
}}

#file-buttons Button {{
    height: 1;
    min-height: 1;
    border: none;
    background: transparent;
    margin-left: 2;
}}

#upload {{
    color: {PRIMARY};
}}

#upload:hover, #upload:focus {{
    color: {TEXT};
    background: {PRIMARY};
}}

#skip {{
    color: {TEXT_MUTED};
}}

#skip:hover, #skip:focus {{
    color: {TEXT};
    background: {BORDER};
}}
"""

PROMPT_EDITOR_CSS = f"""
Screen {{
    background: {BG};
    color: {TEXT};
}}

#editor_container {{
    height: 100%;
    padding: 1 2;
    background: {BG};
}}

#editor_title {{
    color: {PRIMARY};
    text-style: bold;
    margin-bottom: 0;
}}

#editor_subtitle {{
    color: {TEXT_MUTED};
    margin-bottom: 1;
}}

#editor_body {{
    height: 1fr;
    background: {PANEL_BG};
    border: round {BORDER};
    padding: 0 1;
    color: {TEXT};
}}

#editor_body:focus {{
    border: round {PRIMARY};
}}

#editor_body .text-area--cursor-line {{
    background: transparent;
}}

#editor_body > .text-area--cursor {{
    color: {PRIMARY};
    background: {PRIMARY};
}}

#editor_status {{
    height: 1;
    margin-top: 1;
    color: {TEXT_MUTED};
}}

#editor_buttons {{
    height: auto;
    align: right middle;
    margin-top: 1;
}}

#editor_buttons Button {{
    height: 1;
    min-height: 1;
    border: none;
    background: transparent;
    margin-left: 2;
}}

#save_prompt {{
    color: {PRIMARY};
}}

#save_prompt:hover, #save_prompt:focus {{
    color: {TEXT};
    background: {PRIMARY};
}}

#cancel_prompt {{
    color: {TEXT_MUTED};
}}

#cancel_prompt:hover, #cancel_prompt:focus {{
    color: {TEXT};
    background: {BORDER};
}}
"""

AGENT_WIZARD_CSS = f"""
Screen {{
    background: {BG};
    color: {TEXT};
}}

#wizard_container {{
    height: 100%;
    padding: 1 2;
    background: {BG};
}}

#wizard_title {{
    color: {PRIMARY};
    text-style: bold;
}}

#wizard_step {{
    color: {TEXT_MUTED};
    margin-bottom: 1;
}}

#wizard_error {{
    color: {DANGER};
    text-style: bold;
    height: auto;
    margin-bottom: 1;
}}

#step_body {{
    height: 1fr;
    background: transparent;
}}

.field_label {{
    color: {TEXT_DIM};
    text-style: bold;
    margin-top: 1;
    margin-bottom: 0;
}}

.field_hint {{
    color: {TEXT_MUTED};
    margin-bottom: 0;
}}

Input {{
    background: {PANEL_BG};
    border: round {BORDER};
    color: {TEXT};
    margin-bottom: 0;
}}

Input:focus {{
    border: round {PRIMARY};
}}

Select {{
    background: {PANEL_BG};
    border: round {BORDER};
    color: {TEXT};
}}

Select:focus {{
    border: round {PRIMARY};
}}

SelectionList {{
    height: 1fr;
    background: {PANEL_BG};
    border: round {BORDER};
    color: {TEXT};
    padding: 0 1;
}}

SelectionList:focus {{
    border: round {PRIMARY};
}}

#prompt_area {{
    height: 1fr;
    background: {PANEL_BG};
    border: round {BORDER};
    padding: 0 1;
    color: {TEXT};
}}

#prompt_area:focus {{
    border: round {PRIMARY};
}}

#prompt_area .text-area--cursor-line {{
    background: transparent;
}}

#prompt_area > .text-area--cursor {{
    color: {PRIMARY};
    background: {PRIMARY};
}}

#review_panel {{
    height: 1fr;
    background: {PANEL_BG};
    border: round {BORDER};
    padding: 1;
    color: {TEXT};
}}

#wizard_footer {{
    height: auto;
    margin-top: 1;
    layout: horizontal;
}}

#wizard_keymap {{
    width: 1fr;
    color: {TEXT_MUTED};
    content-align: left middle;
}}

#wizard_buttons {{
    width: auto;
    height: auto;
    align: right middle;
}}

#wizard_buttons Button {{
    height: 1;
    min-height: 1;
    border: none;
    background: transparent;
    margin-left: 2;
}}

#btn_back {{
    color: {TEXT_MUTED};
}}

#btn_back:hover, #btn_back:focus {{
    color: {TEXT};
    background: {BORDER};
}}

#btn_next, #btn_confirm {{
    color: {PRIMARY};
}}

#btn_next:hover, #btn_next:focus,
#btn_confirm:hover, #btn_confirm:focus {{
    color: {TEXT};
    background: {PRIMARY};
}}

#btn_cancel {{
    color: {TEXT_MUTED};
}}

#btn_cancel:hover, #btn_cancel:focus {{
    color: {TEXT};
    background: {BORDER};
}}
"""
