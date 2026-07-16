"""Dispatcher — the Textual TUI application (control plane)."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header

from claude_dispatch.config import load_config
from claude_dispatch.ui.views.jobs import JobsView


class DispatcherApp(App):
    """k9s-style TUI for orchestrating parallel Claude Code sessions."""

    TITLE = "claude-dispatch"
    CSS_PATH = None

    BINDINGS = [
        Binding("n", "new_job", "New job"),
        Binding("k", "kill", "Kill"),
        Binding("r", "resume", "Resume"),
        Binding("c", "costs", "Costs"),
        Binding("question_mark", "help", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.jobs: list = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield JobsView(jobs=self.jobs)
        yield Footer()

    def action_new_job(self) -> None:
        """Open prompt bar to create a new job."""
        # TODO: open PromptBar widget, collect description, spawn Job
        pass

    def action_kill(self) -> None:
        """Kill the selected job or agent."""
        # TODO: delegate to focused view
        pass

    def action_resume(self) -> None:
        """Resume a past job from history."""
        # TODO: open history picker, load session IDs from DB
        pass

    def action_costs(self) -> None:
        """Show cost breakdown overlay."""
        # TODO: open CostOverlay widget
        pass
