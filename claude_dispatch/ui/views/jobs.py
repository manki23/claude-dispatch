"""Jobs view — top-level list of all running and past jobs."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Static


class JobsView(Static):
    """Displays the list of Jobs with status, phase, agent count, cost, and age."""

    BINDINGS = [
        Binding("enter", "drill_in", "Drill in"),
        Binding("m", "message_job", "Message job"),
    ]

    def __init__(self, jobs: list, **kwargs) -> None:
        super().__init__(**kwargs)
        self.jobs = jobs

    def compose(self) -> ComposeResult:
        table = DataTable()
        table.add_columns("NAME", "STATUS", "PHASE", "AGENTS", "COST", "AGE")
        for job in self.jobs:
            table.add_row(
                job.description,
                job.status.value,
                job.phase.value,
                job.agent_count,
                f"${job.cost_usd:.2f}",
                "—",
            )
        yield table

    def action_drill_in(self) -> None:
        """Navigate to the Agents view for the selected job."""
        # TODO: push AgentsView onto the app screen stack
        pass

    def action_message_job(self) -> None:
        """Open prompt bar to send a message to the selected job."""
        # TODO: open PromptBar widget, call job.send_message()
        pass
