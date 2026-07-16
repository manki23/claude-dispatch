"""Dispatcher — the Textual TUI application (control plane)."""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from claude_dispatch.config import Config, load_config
from claude_dispatch.job import Job


class DispatcherApp(App):
    """k9s-style TUI for orchestrating parallel Claude Code sessions."""

    TITLE = "claude-dispatch"
    CSS_PATH = Path(__file__).parent / "app.tcss"

    def __init__(self, jobs: list[Job] | None = None, config: Config | None = None) -> None:
        super().__init__()
        self.config = config or load_config()
        self.jobs: list[Job] = jobs or []

    def on_mount(self) -> None:
        from claude_dispatch.ui.screens.main import MainScreen
        self.push_screen(MainScreen(jobs=self.jobs))
