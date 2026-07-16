"""Agents view — list of agents inside a Job."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Static

from claude_dispatch.job import Job


class AgentsView(Static):
    """Displays agents for a given Job with type, model, status, cost, last action."""

    BINDINGS = [
        Binding("enter", "view_logs", "View logs"),
        Binding("escape", "go_back", "Back"),
        Binding("k", "kill_agent", "Kill agent"),
    ]

    def __init__(self, job: Job, **kwargs) -> None:
        super().__init__(**kwargs)
        self.job = job

    def compose(self) -> ComposeResult:
        table = DataTable()
        table.add_columns("TYPE", "MODEL", "STATUS", "COST", "LAST ACTION")
        for agent in self.job.agents:
            table.add_row(
                agent.spec.type.value,
                agent.model,
                agent.status.value,
                f"${agent.cost_usd:.3f}",
                agent.last_action or "—",
            )
        yield table

    def action_view_logs(self) -> None:
        """Navigate to the Logs view for the selected agent."""
        # TODO: push LogsView onto the app screen stack
        pass

    def action_go_back(self) -> None:
        """Go back to the Jobs view."""
        # TODO: pop current screen
        pass

    def action_kill_agent(self) -> None:
        """Kill the selected agent."""
        # TODO: call agent.kill()
        pass
