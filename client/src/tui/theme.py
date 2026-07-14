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
TEXT_FAINT = "#525252"
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
    background: transparent;
    border: round {BORDER};
    margin: 0;
    padding: 0;
    layout: horizontal;
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
