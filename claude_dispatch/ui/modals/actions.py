"""ActionsModal — generic labeled-key choice overlay.

Usage:
    self.app.push_screen(
        ActionsModal(
            title="Job not running (status: done)",
            choices=[
                ("v", "Remove from view"),
                ("h", "Remove from view + history"),
            ],
        ),
        callback=lambda result: ...,
    )
    # result is one of the choice keys ("v", "h"), or None if Esc pressed.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Label, Static


class ActionsModal(ModalScreen[str | None]):
    """Small overlay listing labeled key choices. Returns the pressed key or None."""

    DEFAULT_CSS = """
    ActionsModal {
        align: center middle;
    }
    #actions-dialog {
        width: auto;
        min-width: 40;
        max-width: 70;
        height: auto;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    #actions-title {
        color: $warning;
        text-style: bold;
        margin-bottom: 1;
    }
    .action-row {
        height: 1;
        color: $text;
    }
    #actions-hint {
        color: $text-muted;
        margin-top: 1;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, title: str, choices: list[tuple[str, str]]) -> None:
        super().__init__()
        self._title = title
        self._choices = choices  # [(key, label), ...]

    def compose(self) -> ComposeResult:
        with Static(id="actions-dialog"):
            yield Label(self._title, id="actions-title")
            for key, label in self._choices:
                yield Label(
                    f"  [dim][[/dim][bold]{key}[/bold][dim]][/dim]  {label}",
                    classes="action-row",
                )
            yield Label("  [dim][Esc][/dim]  Cancel", classes="action-row")
            yield Label("", id="actions-hint")

    def on_key(self, event: Key) -> None:
        for key, _ in self._choices:
            if event.key == key:
                event.stop()
                self.dismiss(key)
                return

    def action_cancel(self) -> None:
        self.dismiss(None)
