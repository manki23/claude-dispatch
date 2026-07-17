"""MainScreen — top-level Jobs list (the Dispatcher home view)."""

from __future__ import annotations

import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Label

from claude_dispatch.job import Job, JobStatus

# ASCII logo — pyfiglet "small" font output for "DISPATCHER".
# Lines ending with \ get a trailing space before [/cyan] to avoid Rich
# treating \[ as an escaped bracket and rendering "[/cyan]" as literal text.
_LOGO = (
    "[cyan] ___ ___ ___ ___  _ _____ ___ _  _ ___ ___ [/cyan]\n"
    "[cyan]|   \\_ _/ __| _ \\/_\\_   _/ __| || | __| _ \\ [/cyan]\n"
    "[cyan]| |) | |\\__ \\  _/ _ \\| || (__| __ | _||   /[/cyan]\n"
    "[cyan]|___/___|___/_|/_/ \\_\\_| \\___|_||_|___|_|_\\ [/cyan]"
)


# Shortcut hints — two columns, one pair per row (k9s style)
def _key(k: str) -> str:
    return f"[dim]<[/dim][bold]{k}[/bold][dim]>[/dim]"


_KEY_HINTS = (
    f"  {_key('n')}  New job       {_key('d')}  Chat\n"
    f"  {_key('m')}  Msg agent     {_key('c')}  Cost\n"
    f"  {_key('k')}  Kill job      {_key('?')}  Help\n"
    f"  {_key('r')}  Resume        {_key('q')}  Quit\n"
    f"  {_key('ctrl+p')}  Palette"
)

_STATUS_ICONS: dict[str, str] = {
    JobStatus.RUNNING: "[green]●[/green]",
    JobStatus.DONE: "[dim green]✓[/dim green]",
    JobStatus.FAILED: "[red]✗[/red]",
    JobStatus.KILLED: "[dim red]⊘[/dim red]",
}


def _fmt_age(created_at: float) -> str:
    """Format seconds-since-epoch as a human age string."""
    secs = int(time.time() - created_at)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    return f"{secs // 3600}h"


class MainScreen(Screen[None]):
    """Home screen: list of all Jobs with live status, phase, agents, cost, age."""

    BINDINGS = [
        Binding("n", "new_job", "New job", show=True),
        Binding("m", "message_job", "Message job", show=True),
        Binding("k", "kill_job", "Kill job", show=True),
        Binding("r", "resume_job", "Resume", show=True),
        Binding("d", "dispatcher", "Chat", show=True),
        Binding("c", "show_costs", "Costs", show=True),
        Binding("question_mark", "show_help", "Help", show=True),
        Binding("q", "quit", "Quit", show=True),
        Binding("space", "toggle_select", "Select", show=True),
        Binding("shift+space", "range_select", "Range select", show=False),
    ]

    def __init__(self, jobs: list[Job]) -> None:
        super().__init__()
        self.jobs = jobs
        self._selected: set[str] = set()
        self._anchor_row: int | None = None

    def compose(self) -> ComposeResult:
        # k9s-style header: one horizontal band split into 3 columns
        with Horizontal(id="dispatch-header"):
            yield Label("", id="header-context")  # left: version/repos/jobs/cost
            yield Label(_KEY_HINTS, id="header-keys")  # middle: shortcuts in 2 cols
            yield Label(_LOGO, id="header-logo")  # right: DISPATCHER logo
        yield DataTable(id="jobs-table", cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one("#jobs-table", DataTable)
        table.add_columns("", "", "NAME", "PHASE", "AGENTS", "COST", "AGE")
        self._refresh()
        self.set_interval(1.0, self._refresh)

    def _refresh(self) -> None:
        # Update header context (4 lines to match logo height)
        running = sum(1 for j in self.jobs if j.status == JobStatus.RUNNING)
        total_jobs = len(self.jobs)
        total_cost = sum(j.cost_usd for j in self.jobs)
        try:
            cfg = self.app.config  # type: ignore[attr-defined]
            n_repos = len(cfg.repos)
        except AttributeError:
            n_repos = 0
        from claude_dispatch import __version__

        run_color = "green" if running else "dim"
        jobs_line = f"[{run_color}]{running}[/{run_color}] running / {total_jobs} total"
        self.query_one("#header-context", Label).update(
            f" [dim]Version:[/dim] {__version__}\n"
            f" [dim]Repos:[/dim]   {n_repos}\n"
            f" [dim]Jobs:[/dim]    {jobs_line}\n"
            f" [dim]Cost:[/dim]    [bold]${total_cost:.4f}[/bold]"
        )

        # Update table
        table = self.query_one("#jobs-table", DataTable)
        cursor_row = table.cursor_row
        table.clear()
        for job in self.jobs:
            running_agents = sum(1 for a in job.agents if a.status.value == "running")
            total_agents = len(job.agents)
            table.add_row(
                "☑" if job.job_id in self._selected else "☐",
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

    def action_toggle_select(self) -> None:
        item = self._selected_job()
        if not item:
            return
        table = self.query_one("#jobs-table", DataTable)
        job_id = item.job_id
        if job_id in self._selected:
            self._selected.discard(job_id)
            self._anchor_row = None
        else:
            self._selected.add(job_id)
            self._anchor_row = table.cursor_row
        self._refresh()

    def action_range_select(self) -> None:
        """Select all jobs from the anchor row to the current cursor row (inclusive)."""
        if not self.jobs:
            return
        table = self.query_one("#jobs-table", DataTable)
        current_row = table.cursor_row
        anchor = self._anchor_row if self._anchor_row is not None else current_row
        lo, hi = min(anchor, current_row), max(anchor, current_row)
        for idx in range(lo, min(hi + 1, len(self.jobs))):
            self._selected.add(self.jobs[idx].job_id)
        self._anchor_row = None
        self._refresh()

    def action_new_job(self) -> None:
        from claude_dispatch.ui.modals.prompt import PromptModal

        def on_name(instructions: str, name: str | None) -> None:
            display = (name or "").strip() or instructions[:60]
            from claude_dispatch.job import Job

            job = Job(description=display, instructions=instructions, config=self.app.config)  # type: ignore[attr-defined]
            self.jobs.append(job)
            self._refresh()
            self.app.run_worker(job.run(), exclusive=False)

        def on_instructions(instructions: str | None) -> None:
            if not instructions:
                return
            # Step 2: short display name (Esc or blank → auto-truncate from instructions)
            self.app.push_screen(
                PromptModal(
                    label="Job name (optional) >",
                    placeholder="short name for jobs list (blank = auto)",
                ),
                callback=lambda name: on_name(instructions, name),
            )

        self.app.push_screen(
            PromptModal(label="Task >", placeholder="describe the task in full detail…"),
            callback=on_instructions,
        )

    def action_message_job(self) -> None:
        job = self._selected_job()
        if not job:
            self.notify("No job selected", severity="warning")
            return
        from claude_dispatch.ui.modals.prompt import PromptModal

        def on_dismiss(message: str | None) -> None:
            if message:
                self.app.run_worker(job.send_message(message), exclusive=False)

        self.app.push_screen(
            PromptModal(
                label=f"→ {job.description[:30]} >",
                placeholder="message for the job…",
            ),
            callback=on_dismiss,
        )

    def action_drill_in(self) -> None:
        job = self._selected_job()
        if job:
            from claude_dispatch.ui.screens.agents import AgentsScreen

            self.app.pop_to_main()  # type: ignore[attr-defined]
            self.app.push_screen(AgentsScreen(job=job))

    def action_kill_job(self) -> None:
        targets = [j for j in self.jobs if j.job_id in self._selected] or (
            [self._selected_job()] if self._selected_job() else []
        )
        if not targets:
            self.notify("No job selected", severity="warning")
            return

        running = [j for j in targets if j.status == JobStatus.RUNNING]
        not_running = [j for j in targets if j.status != JobStatus.RUNNING]

        for j in running:
            j.kill()

        if len(targets) == 1 and not running:
            # Single non-running job — original behavior
            job = not_running[0]
            from claude_dispatch.ui.modals.actions import ActionsModal

            def on_choice_single(result: str | None) -> None:
                if result == "v":
                    self.jobs.remove(job)
                    self._selected.discard(job.job_id)
                    self._refresh()
                    self.notify("Removed from view", severity="information")
                elif result == "h":
                    self.jobs.remove(job)
                    self._selected.discard(job.job_id)
                    self._refresh()
                    self.app.run_worker(self._delete_from_history(job.job_id), exclusive=False)

            self.app.push_screen(
                ActionsModal(
                    title=f"Job not running (status: {job.status.value})",
                    choices=[
                        ("v", "Remove from view"),
                        ("h", "Remove from view + history"),
                    ],
                ),
                callback=on_choice_single,
            )
        elif not_running:
            # Bulk: offer options for non-running remainder
            from claude_dispatch.ui.modals.actions import ActionsModal

            title = f"{len(not_running)} job(s) not running"
            if running:
                title += f" ({len(running)} killed)"

            not_running_snapshot = list(not_running)

            def on_choice_bulk(result: str | None) -> None:
                if result == "v":
                    for j in not_running_snapshot:
                        self.jobs.remove(j)
                        self._selected.discard(j.job_id)
                    self._refresh()
                    self.notify(
                        f"{len(not_running_snapshot)} job(s) removed from view",
                        severity="information",
                    )
                elif result == "h":
                    for j in not_running_snapshot:
                        self.jobs.remove(j)
                        self._selected.discard(j.job_id)
                    self._refresh()
                    for j in not_running_snapshot:
                        self.app.run_worker(self._delete_from_history(j.job_id), exclusive=False)

            self.app.push_screen(
                ActionsModal(
                    title=title,
                    choices=[
                        ("v", f"Remove {len(not_running)} from view"),
                        ("h", f"Remove {len(not_running)} from view + history"),
                    ],
                ),
                callback=on_choice_bulk,
            )
        else:
            # All were running → all killed
            self._selected.clear()
            self._refresh()
            self.notify(f"{len(running)} job(s) killed", severity="information")

    async def _delete_from_history(self, job_id: str) -> None:
        from claude_dispatch.db import delete_job

        await delete_job(job_id)
        self.notify("Removed from view and history", severity="information")

    def action_resume_job(self) -> None:
        """If items selected, resume them directly; otherwise open picker."""
        if self._selected:
            for job_id in list(self._selected):
                self.app.run_worker(self._do_resume(job_id), exclusive=False)
            self._selected.clear()
            self._refresh()
            return
        self.app.run_worker(self._open_resume_picker(), exclusive=False)

    async def _open_resume_picker(self) -> None:
        from claude_dispatch.db import list_jobs
        from claude_dispatch.ui.modals.resume import ResumeModal

        past_jobs = await list_jobs()
        if not past_jobs:
            self.notify("No past jobs found in DB", severity="warning")
            return

        def on_dismiss(job_ids: list[str] | None) -> None:
            for job_id in job_ids or []:
                self.app.run_worker(self._do_resume(job_id), exclusive=False)

        self.app.push_screen(ResumeModal(jobs=past_jobs), callback=on_dismiss)

    async def _do_resume(self, job_id: str) -> None:
        """Worker body: reconstruct job from DB and push AgentsScreen."""
        try:
            await self._resume_job(job_id)
        except Exception as exc:
            self.notify(f"Resume failed: {exc}", severity="error")

    async def _resume_job(self, job_id: str) -> None:
        """Reconstruct a job from memory or DB and push AgentsScreen."""
        # Check if job is already loaded in this session
        existing = next((j for j in self.jobs if j.job_id == job_id), None)
        if existing:
            from claude_dispatch.ui.screens.agents import AgentsScreen

            self.app.push_screen(AgentsScreen(job=existing))
            return

        # Try to reconstruct from DB
        from claude_dispatch.db import list_agents, list_jobs

        known = await list_jobs()
        row = next((r for r in known if r["job_id"] == job_id), None)
        if row is None:
            self.notify(f"No job found with id '{job_id}'", severity="error")
            return

        from claude_dispatch.agent import Agent, AgentSpec, AgentStatus, AgentType
        from claude_dispatch.job import Job, JobStatus

        try:
            job_status = JobStatus(row["status"])
        except (ValueError, TypeError):
            job_status = JobStatus.DONE

        job = Job(
            description=row["description"] or "",
            instructions=row.get("instructions") or "",
            config=self.app.config,  # type: ignore[attr-defined]
            job_id=job_id,
            status=job_status,
        )
        agent_rows = await list_agents(job_id)
        for ar in agent_rows:
            try:
                agent_type = AgentType(ar["agent_type"])
            except ValueError:
                continue
            try:
                agent_status = AgentStatus(ar["status"])
            except (ValueError, TypeError):
                agent_status = AgentStatus.DONE
            # Jobs loaded from DB are never still running — the process is dead.
            # Force RUNNING → DONE so the agent is resumable via send_message.
            if agent_status == AgentStatus.RUNNING:
                agent_status = AgentStatus.DONE
            agent = Agent(
                spec=AgentSpec(type=agent_type),
                job_id=job_id,
                agent_id=f"{job_id}-{ar['agent_type']}",
                status=agent_status,
                session_id=ar["session_id"],
                cost_usd=ar["cost_usd"] or 0.0,
            )
            job.agents.append(agent)

        self.jobs.append(job)
        self._refresh()
        from claude_dispatch.ui.screens.agents import AgentsScreen

        self.app.push_screen(AgentsScreen(job=job))

    def action_dispatcher(self) -> None:
        self.app.open_dispatcher_conversation()  # type: ignore[attr-defined]

    def action_show_costs(self) -> None:
        from claude_dispatch.ui.modals.cost import CostModal

        self.app.push_screen(CostModal(jobs=self.jobs))

    def action_show_help(self) -> None:
        from claude_dispatch.ui.modals.help import HelpModal

        self.app.push_screen(HelpModal())

    def action_quit(self) -> None:
        self.app.exit()
