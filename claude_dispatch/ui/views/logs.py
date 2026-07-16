"""Logs view — streaming output of a single Agent session."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import RichLog, Static

from claude_dispatch.agent import Agent


class LogsView(Static):
    """Streams raw SDK output for a single agent."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
    ]

    def __init__(self, agent: Agent, **kwargs) -> None:
        super().__init__(**kwargs)
        self.agent = agent

    def compose(self) -> ComposeResult:
        log = RichLog(highlight=True, markup=True)
        for line in self.agent.log_lines:
            log.write(line)
        yield log

    def action_go_back(self) -> None:
        """Go back to the Agents view."""
        # TODO: pop current screen
        pass
