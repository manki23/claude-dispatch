"""CostModal — per-job and per-agent cost breakdown overlay."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static


class CostModal(ModalScreen[None]):
    """Full cost breakdown: per-agent rows grouped by job."""

    DEFAULT_CSS = """
    CostModal {
        align: center middle;
    }
    #cost-dialog {
        width: 90%;
        max-width: 120;
        min-width: 55;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    #cost-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #cost-table {
        height: auto;
        max-height: 20;
    }
    #cost-total {
        color: $text;
        text-style: bold;
        margin-top: 1;
    }
    #cost-close {
        color: $text-muted;
        margin-top: 1;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Close", show=False),
        Binding("c", "dismiss_modal", "Close", show=False),
    ]

    def __init__(self, jobs: list) -> None:
        super().__init__()
        self._jobs = jobs

    def compose(self) -> ComposeResult:
        with Static(id="cost-dialog"):
            yield Label("Cost Breakdown", id="cost-title")
            table = DataTable(id="cost-table", show_cursor=False)
            yield table
            total = sum(j.cost_usd for j in self._jobs)
            yield Label(f"Total: ${total:.4f}", id="cost-total")
            yield Label("[ Esc ] close", id="cost-close")

    def on_mount(self) -> None:
        table = self.query_one("#cost-table", DataTable)
        table.add_columns("JOB", "AGENT", "MODEL", "STATUS", "COST")
        for job in self._jobs:
            for agent in job.agents:
                table.add_row(
                    job.description[:25],
                    agent.spec.type.value,
                    agent.model,
                    agent.status.value,
                    f"${agent.cost_usd:.4f}",
                )
            job_total = sum(a.cost_usd for a in job.agents)
            table.add_row("", "", "", "[dim]job total[/dim]", f"[bold]${job_total:.4f}[/bold]")

    def action_dismiss_modal(self) -> None:
        self.dismiss()
