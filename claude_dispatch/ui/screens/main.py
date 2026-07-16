"""MainScreen — top-level Jobs list (the Dispatcher home view)."""

from __future__ import annotations

import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Label

from claude_dispatch.job import Job, JobStatus

_STATUS_ICONS: dict[str, str] = {
    JobStatus.RUNNING: "[green]●[/green]",
    JobStatus.DONE:    "[dim green]✓[/dim green]",
    JobStatus.FAILED:  "[red]✗[/red]",
    JobStatus.KILLED:  "[dim red]⊘[/dim red]",
}


def _fmt_age(created_at: float) -> str:
    """Format seconds-since-epoch as a human age string."""
    secs = int(time.time() - created_at)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    return f"{secs // 3600}h"


class MainScreen(Screen):
    """Home screen: list of all Jobs with live status, phase, agents, cost, age."""

    BINDINGS = [
        Binding("n", "new_job", "New job", show=True),
        Binding("m", "message_job", "Message job", show=True),
        Binding("k", "kill_job", "Kill job", show=True),
        Binding("r", "resume_job", "Resume", show=True),
        Binding("c", "show_costs", "Costs", show=True),
        Binding("question_mark", "show_help", "Help", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self, jobs: list[Job]) -> None:
        super().__init__()
        self.jobs = jobs

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("", id="main-stats")
            yield DataTable(id="jobs-table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#jobs-table", DataTable)
        table.add_columns("", "NAME", "PHASE", "AGENTS", "COST", "AGE")
        self._refresh()
        self.set_interval(1.0, self._refresh)

    def _refresh(self) -> None:
        # Update header stats
        running = sum(1 for j in self.jobs if j.status == JobStatus.RUNNING)
        total_cost = sum(j.cost_usd for j in self.jobs)
        self.query_one("#main-stats", Label).update(
            f"[dim]Jobs running:[/dim] [bold]{running}[/bold]   "
            f"[dim]Total cost:[/dim] [bold]${total_cost:.4f}[/bold]"
        )

        # Update table
        table = self.query_one("#jobs-table", DataTable)
        cursor_row = table.cursor_row
        table.clear()
        for job in self.jobs:
            running_agents = sum(
                1 for a in job.agents
                if a.status.value == "running"
            )
            total_agents = len(job.agents)
            table.add_row(
                _STATUS_ICONS.get(job.status, ""),
                job.description,
                job.phase.value if job.status == JobStatus.RUNNING else "[dim]—[/dim]",
                f"{running_agents}/{total_agents}" if total_agents else "[dim]—[/dim]",
                f"${job.cost_usd:.4f}",
                _fmt_age(job.created_at),
                key=job.job_id,
            )
        if cursor_row < len(self.jobs):
            table.move_cursor(row=cursor_row)

    def _selected_job(self) -> Job | None:
        table = self.query_one("#jobs-table", DataTable)
        if not self.jobs:
            return None
        row = table.cursor_row
        if row < len(self.jobs):
            return self.jobs[row]
        return None

    # ── DataTable events ───────────────────────────────────────────

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """DataTable fires RowSelected on Enter — drill into the selected job."""
        self.action_drill_in()

    # ── Actions ────────────────────────────────────────────────────

    async def action_new_job(self) -> None:
        from claude_dispatch.ui.modals.prompt import PromptModal

        description = await self.app.push_screen_wait(
            PromptModal(label="New job >", placeholder="describe the task…")
        )
        if description:
            from claude_dispatch.job import Job
            job = Job(description=description, config=self.app.config)
            self.jobs.append(job)
            self._refresh()
            # TODO: kick off job.run() as a background task

    async def action_message_job(self) -> None:
        job = self._selected_job()
        if not job:
            return
        from claude_dispatch.ui.modals.prompt import PromptModal

        message = await self.app.push_screen_wait(
            PromptModal(
                label=f"→ {job.description[:30]} >",
                placeholder="message for the job…",
            )
        )
        if message:
            job.send_message(message)

    def action_drill_in(self) -> None:
        job = self._selected_job()
        if job:
            from claude_dispatch.ui.screens.agents import AgentsScreen
            self.app.push_screen(AgentsScreen(job=job))

    def action_kill_job(self) -> None:
        job = self._selected_job()
        if job and job.status == JobStatus.RUNNING:
            job.kill()
            self._refresh()

    async def action_resume_job(self) -> None:
        from claude_dispatch.ui.modals.prompt import PromptModal

        job_id = await self.app.push_screen_wait(
            PromptModal(label="Resume job-id >", placeholder="e.g. abc123")
        )
        if job_id:
            # TODO: load session from DB and push AgentsScreen
            pass

    def action_show_costs(self) -> None:
        from claude_dispatch.ui.modals.cost import CostModal
        self.app.push_screen(CostModal(jobs=self.jobs))

    def action_show_help(self) -> None:
        from claude_dispatch.ui.modals.help import HelpModal
        self.app.push_screen(HelpModal())

    def action_quit(self) -> None:
        self.app.exit()
