"""PromptModal — bottom-of-screen input bar, like k9s command mode."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class PromptModal(ModalScreen[str | None]):
    """
    A modal input bar docked to the bottom of the screen.
    Dismisses with the entered text on Enter, or None on Escape.
    """

    DEFAULT_CSS = """
    PromptModal {
        align: center bottom;
        background: transparent;
    }
    #prompt-container {
        height: 3;
        background: $primary-darken-3;
        border-top: solid $primary;
        padding: 0 1;
        width: 100%;
        layout: horizontal;
    }
    #prompt-label {
        width: auto;
        color: $accent;
        text-style: bold;
        margin-right: 1;
        content-align: left middle;
    }
    #prompt-input {
        width: 1fr;
        border: none;
        background: transparent;
        color: $text;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, label: str = ">", placeholder: str = "") -> None:
        super().__init__()
        self._label = label
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Horizontal(id="prompt-container"):
            yield Label(self._label, id="prompt-label")
            yield Input(placeholder=self._placeholder, id="prompt-input")

    def on_mount(self) -> None:
        self.query_one("#prompt-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        self.dismiss(value if value else None)

    def action_cancel(self) -> None:
        self.dismiss(None)
