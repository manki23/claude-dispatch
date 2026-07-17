"""PromptModal — bottom-of-screen input bar, like k9s command mode."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Label

from claude_dispatch.ui.widgets.chat_input import ChatInput


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
        height: auto;
        max-height: 9;
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
        height: auto;
        max-height: 6;
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
            yield ChatInput(placeholder=self._placeholder, id="prompt-input")

    def on_mount(self) -> None:
        self.query_one("#prompt-input", ChatInput).focus()

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        chat_input = self.query_one("#prompt-input", ChatInput)
        value = chat_input.get_text_and_clear()
        self.dismiss(value if value else None)

    def action_cancel(self) -> None:
        self.dismiss(None)
