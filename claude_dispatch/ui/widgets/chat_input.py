"""Shared ChatInput widget — wrapping TextArea with multi-line paste compaction."""

from __future__ import annotations

from textual.events import Key, Paste
from textual.widgets import TextArea

_PASTE_PLACEHOLDER = "[Pasted text #{n} +{extra} lines]"
_paste_counter: int = 0


class ChatInput(TextArea):
    """Single-line-looking input that wraps long text and handles multi-line paste.

    - Enter       → submit (fire Submitted message)
    - Shift+Enter → insert newline
    - Multi-line paste → stores full text in _paste_buffer, shows preview placeholder
    """

    BINDINGS = []  # no extra bindings — enter handled via on_key

    class Submitted(TextArea.Changed):
        """Fired when the user presses Enter to send."""

    def __init__(self, placeholder: str = "", id: str = "chat-input") -> None:  # noqa: A002
        super().__init__("", soft_wrap=True, show_line_numbers=False, id=id)
        self._placeholder = placeholder
        self._paste_buffer: str | None = None

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.action_submit_message()
        elif event.key == "shift+enter":
            event.prevent_default()
            event.stop()
            self.action_insert_newline()

    async def _on_paste(self, event: Paste) -> None:
        global _paste_counter
        text = event.text
        lines = text.splitlines()
        if len(lines) <= 1:
            self._paste_buffer = None
            await super()._on_paste(event)
            return

        event.prevent_default()
        _paste_counter += 1
        self._paste_buffer = text
        extra = len(lines) - 1
        preview = f"[Pasted text #{_paste_counter} +{extra} lines]"
        self.clear()
        self.insert(preview)

    def action_submit_message(self) -> None:
        text = self._paste_buffer if self._paste_buffer is not None else self.text
        text = text.strip()
        if not text:
            return
        self.post_message(self.Submitted(self))

    def action_insert_newline(self) -> None:
        self.insert("\n")

    def get_text_and_clear(self) -> str:
        """Return pending text (paste buffer or typed) and reset state."""
        text = self._paste_buffer if self._paste_buffer is not None else self.text
        self._paste_buffer = None
        self.clear()
        return text.strip()
