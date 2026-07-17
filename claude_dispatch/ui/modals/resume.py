"""ResumeModal — pick a past job from DB to resume."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static

_STATUS_STYLE: dict[str, str] = {
    "done": "[dim green]done[/dim green]",
    "running": "[green]running[/green]",
    "failed": "[red]failed[/red]",
    "killed": "[dim red]killed[/dim red]",
}


class ResumeModal(ModalScreen[list[str] | None]):
    """Show all known jobs (DB) and let the user select one or more to resume.

    Returns a list of selected job_ids, or None on cancel.
    """

    DEFAULT_CSS = """
    ResumeModal {
        align: center middle;
    }
    #resume-dialog {
        width: 90%;
        max-width: 110;
        min-width: 60;
        height: auto;
        max-height: 80%;
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
        max-height: 12;
    }
    #resume-preview {
        height: 3;
        border: solid $primary-darken-2;
        background: $surface-darken-1;
        color: $text-muted;
        padding: 0 1;
        margin-top: 1;
    }
    #resume-hint {
        color: $text-muted;
        margin-top: 1;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("space", "toggle_select", "Select", show=False),
    ]

    def __init__(self, jobs: list[dict[str, Any]]) -> None:
        super().__init__()
        self._jobs = jobs
        self._selected: set[str] = set()

    def compose(self) -> ComposeResult:
        with Static(id="resume-dialog"):
            yield Label("Resume a past job", id="resume-title")
            table: DataTable[str] = DataTable(id="resume-table", cursor_type="row")
            yield table
            yield Label("", id="resume-preview")
            yield Label("[ Space ] select   [ Enter ] open   [ Esc ] cancel", id="resume-hint")

    def on_mount(self) -> None:
        table = self.query_one("#resume-table", DataTable)
        table.add_columns("", "#", "NAME", "STATUS", "COST", "UPDATED")
        for idx, job in enumerate(self._jobs, start=1):
            name = (job.get("description") or "—")[:55]
            status = job.get("status") or "—"
            status_markup = _STATUS_STYLE.get(status, status)
            table.add_row(
                "☐",
                f"[dim]{idx}[/dim]",
                name,
                status_markup,
                f"${job.get('cost_usd') or 0:.4f}",
                (job.get("updated_at") or "")[:16],
                key=job["job_id"],
            )
        table.focus()
        if self._jobs:
            self._update_preview(0)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._update_preview(event.cursor_row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row = event.cursor_row
        if row < len(self._jobs):
            job_id = self._jobs[row]["job_id"]
            if self._selected:
                self.dismiss(list(self._selected))
            else:
                self.dismiss([job_id])

    def action_toggle_select(self) -> None:
        table = self.query_one("#resume-table", DataTable)
        row = table.cursor_row
        if row >= len(self._jobs):
            return
        job_id = self._jobs[row]["job_id"]
        if job_id in self._selected:
            self._selected.discard(job_id)
        else:
            self._selected.add(job_id)
        self._refresh_table()
        self._update_preview(row)

    def _refresh_table(self) -> None:
        table = self.query_one("#resume-table", DataTable)
        cursor_row = table.cursor_row
        table.clear()
        for idx, job in enumerate(self._jobs, start=1):
            name = (job.get("description") or "—")[:55]
            status = job.get("status") or "—"
            status_markup = _STATUS_STYLE.get(status, status)
            job_id = job["job_id"]
            table.add_row(
                "☑" if job_id in self._selected else "☐",
                f"[dim]{idx}[/dim]",
                name,
                status_markup,
                f"${job.get('cost_usd') or 0:.4f}",
                (job.get("updated_at") or "")[:16],
                key=job_id,
            )
        if cursor_row < len(self._jobs):
            table.move_cursor(row=cursor_row)

    def _update_preview(self, row: int) -> None:
        if row >= len(self._jobs):
            return
        job = self._jobs[row]
        name = job.get("description") or "—"
        job_id = job.get("job_id") or "—"
        cost = job.get("cost_usd") or 0.0
        updated = (job.get("updated_at") or "")[:16]
        if self._selected:
            meta = (
                f" [bold]{len(self._selected)} job(s) selected[/bold]"
                f"   [dim]id:[/dim] {job_id}"
                f"   [dim]cost:[/dim] ${cost:.4f}"
                f"   [dim]updated:[/dim] {updated}"
            )
        else:
            meta = (
                f" [dim]id:[/dim] {job_id}"
                f"   [dim]cost:[/dim] ${cost:.4f}"
                f"   [dim]updated:[/dim] {updated}"
            )
        self.query_one("#resume-preview", Label).update(f" [bold]{name}[/bold]\n{meta}")

    def action_cancel(self) -> None:
        self.dismiss(None)
