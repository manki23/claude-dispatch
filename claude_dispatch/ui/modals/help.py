"""HelpModal — keybindings reference overlay."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static

_BINDINGS: list[tuple[str, str, str]] = [
    # (context, key, description)
    ("Global", "q", "Quit"),
    ("Global", "?", "Show this help"),
    ("Global", "c", "Cost breakdown"),
    ("Jobs view", "n", "New job (opens prompt)"),
    ("Jobs view", "Enter", "Drill into selected job"),
    ("Jobs view", "m", "Message selected job"),
    ("Jobs view", "k", "Kill selected job"),
    ("Jobs view", "r", "Resume job from history"),
    ("Agents view", "Enter", "View agent logs"),
    ("Agents view", "k", "Kill selected agent"),
    ("Agents view", "Esc", "Back to Jobs"),
    ("Logs view", "Esc", "Back to Agents"),
    ("Any modal", "Esc", "Close / cancel"),
]


class HelpModal(ModalScreen[None]):
    """Keybindings reference — press ? to open, Esc to close."""

    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
    }
    #help-dialog {
        width: 65;
        height: auto;
        max-height: 35;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    #help-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #help-table {
        height: auto;
        max-height: 25;
    }
    #help-close {
        color: $text-muted;
        margin-top: 1;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Close", show=False),
        Binding("question_mark", "dismiss_modal", "Close", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Static(id="help-dialog"):
            yield Label("Keybindings", id="help-title")
            table = DataTable(id="help-table", show_cursor=False)
            yield table
            yield Label("[ Esc ] close", id="help-close")

    def on_mount(self) -> None:
        table = self.query_one("#help-table", DataTable)
        table.add_columns("CONTEXT", "KEY", "ACTION")
        prev_ctx = None
        for ctx, key, desc in _BINDINGS:
            ctx_display = ctx if ctx != prev_ctx else ""
            table.add_row(f"[dim]{ctx_display}[/dim]", f"[bold]{key}[/bold]", desc)
            prev_ctx = ctx

    def action_dismiss_modal(self) -> None:
        self.dismiss()
