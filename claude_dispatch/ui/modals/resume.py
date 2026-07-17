"""ResumeModal — pick a past job from DB to resume."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static


class ResumeModal(ModalScreen[str | None]):
    """Show all known jobs (DB) and let the user select one to resume.

    Returns the selected job_id string, or None on cancel.
    """

    DEFAULT_CSS = """
    ResumeModal {
        align: center middle;
    }
    #resume-dialog {
        width: 90%;
        max-width: 100;
        min-width: 60;
        height: auto;
        max-height: 70%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    #resume-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #resume-table {
        height: auto;
        max-height: 20;
    }
    #resume-hint {
        color: $text-muted;
        margin-top: 1;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "select", "Resume", show=False),
    ]

    def __init__(self, jobs: list[dict[str, Any]]) -> None:
        super().__init__()
        self._jobs = jobs  # list of dicts from list_jobs()

    def compose(self) -> ComposeResult:
        with Static(id="resume-dialog"):
            yield Label("Resume a past job", id="resume-title")
            table: DataTable[str] = DataTable(id="resume-table", cursor_type="row")
            yield table
            yield Label("[ Enter ] resume   [ Esc ] cancel", id="resume-hint")

    def on_mount(self) -> None:
        table = self.query_one("#resume-table", DataTable)
        table.add_columns("JOB ID", "DESCRIPTION", "STATUS", "COST", "UPDATED")
        for job in self._jobs:
            table.add_row(
                job["job_id"][:12],
                (job["description"] or "—")[:45],
                job["status"] or "—",
                f"${job['cost_usd']:.4f}",
                (job["updated_at"] or "")[:16],
                key=job["job_id"],
            )
        table.focus()

    def action_select(self) -> None:
        table = self.query_one("#resume-table", DataTable)
        if not self._jobs:
            self.dismiss(None)
            return
        row = table.cursor_row
        if row < len(self._jobs):
            self.dismiss(self._jobs[row]["job_id"])

    def action_cancel(self) -> None:
        self.dismiss(None)
