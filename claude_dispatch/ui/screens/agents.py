"""AgentsScreen — list of agents inside a Job."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Label

from claude_dispatch.agent import Agent, AgentStatus
from claude_dispatch.job import Job
from claude_dispatch.ui.widgets.dispatch_header import DispatchHeader, key_hint

_KEY_HINTS = (
    f"  {key_hint('esc')}  Back          {key_hint('d')}  Chat\n"
    f"  {key_hint('m')}  Message        {key_hint('k')}  Kill agent\n"
    f"  {key_hint('space')}  Select"
)

_STATUS_ICONS: dict[str, str] = {
    AgentStatus.RUNNING: "[green]● running[/green]",
    AgentStatus.DONE: "[dim green]✓ done[/dim green]",
    AgentStatus.WAITING: "[dim]○ waiting[/dim]",
    AgentStatus.FAILED: "[red]✗ failed[/red]",
    AgentStatus.KILLED: "[dim red]⊘ killed[/dim red]",
}


class AgentsScreen(Screen[None]):
    """Drill-in view: agents for one Job. Enter → logs. Esc → back."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("ctrl+1", "goto_root", "Dispatcher", show=False, priority=True),
        Binding("d", "dispatcher", "Chat", show=True),
        Binding("m", "message_agent", "Message agent", show=True),
        Binding("k", "kill_agent", "Kill agent", show=True),
        Binding("space", "toggle_select", "Select", show=True),
        Binding("shift+space", "range_select", "Range select", show=False),
    ]

    def __init__(self, job: Job) -> None:
        super().__init__()
        self._job = job
        self._selected: set[str] = set()
        self._anchor_row: int | None = None

    def compose(self) -> ComposeResult:
        yield DispatchHeader(_KEY_HINTS)
        with Vertical():
            yield Label("", id="breadcrumb")
            yield Label(
                f"[dim]phase:[/dim] {self._job.phase.value}  "
                f"[dim]cost:[/dim] ${self._job.cost_usd:.4f}",
                id="agents-header",
            )
            yield DataTable(id="agents-table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        desc = self._job.description[:60]
        self.query_one("#breadcrumb", Label).update(
            f"[dim]<ctrl+1>[/dim] [dim]DISPATCHER[/dim]  ›  [bold]{desc}[/bold]"
        )
        table = self.query_one("#agents-table", DataTable)
        table.add_columns("", "TYPE", "MODEL", "STATUS", "COST", "SESSION", "LAST ACTION")
        self._refresh_table()
        self.set_interval(1.0, self._refresh_table)
        self.set_interval(1.0, self._refresh_header)

    def _refresh_header(self) -> None:
        """Keep header phase/cost in sync with the live job."""
        self.query_one("#agents-header", Label).update(
            f"[dim]phase:[/dim] {self._job.phase.value}  [dim]cost:[/dim] ${self._job.cost_usd:.4f}"
        )

    def _refresh_table(self) -> None:
        table = self.query_one("#agents-table", DataTable)
        cursor_row = table.cursor_row
        table.clear()
        for agent in self._job.agents:
            session_display = (
                f"[dim]{agent.session_id[:12]}…[/dim]" if agent.session_id else "[dim]—[/dim]"
            )
            table.add_row(
                "☑" if agent.agent_id in self._selected else "☐",
                agent.spec.type.value,
                agent.model,
                _STATUS_ICONS.get(agent.status, agent.status.value),
                f"${agent.cost_usd:.4f}",
                session_display,
                agent.last_action or "[dim]—[/dim]",
                key=agent.agent_id,
            )
        # Restore cursor position after refresh
        if cursor_row < len(self._job.agents):
            table.move_cursor(row=cursor_row)

    def _selected_agent(self) -> Agent | None:
        table = self.query_one("#agents-table", DataTable)
        if not self._job.agents:
            return None
        row = table.cursor_row
        if row < len(self._job.agents):
            return self._job.agents[row]
        return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """DataTable fires RowSelected on Enter — drill into agent logs."""
        self.action_view_logs()

    def action_toggle_select(self) -> None:
        agent = self._selected_agent()
        if not agent:
            return
        table = self.query_one("#agents-table", DataTable)
        agent_id = agent.agent_id
        if agent_id in self._selected:
            self._selected.discard(agent_id)
            self._anchor_row = None
        else:
            self._selected.add(agent_id)
            self._anchor_row = table.cursor_row
        self._refresh_table()

    def action_range_select(self) -> None:
        """Select all agents from the anchor row to the current cursor row (inclusive)."""
        if not self._job.agents:
            return
        table = self.query_one("#agents-table", DataTable)
        current_row = table.cursor_row
        anchor = self._anchor_row if self._anchor_row is not None else current_row
        lo, hi = min(anchor, current_row), max(anchor, current_row)
        for idx in range(lo, min(hi + 1, len(self._job.agents))):
            self._selected.add(self._job.agents[idx].agent_id)
        self._anchor_row = None
        self._refresh_table()

    def action_view_logs(self) -> None:
        agent = self._selected_agent()
        if agent:
            from claude_dispatch.ui.screens.logs import LogsScreen

            self.app.pop_to_agents()  # type: ignore[attr-defined]
            self.app.push_screen(LogsScreen(job=self._job, agent=agent))

    def action_message_agent(self) -> None:
        agent = self._selected_agent()
        if not agent:
            self.notify("No agent selected", severity="warning")
            return
        from claude_dispatch.ui.modals.prompt import PromptModal

        agent_type = agent.spec.type.value

        def on_dismiss(message: str | None) -> None:
            if not message:
                return

            async def _deliver() -> None:
                try:
                    delivered = await self._job.send_message(message, agent_type=agent_type)
                    if not delivered:
                        self.notify(
                            f"Could not deliver message to '{agent_type}'",
                            severity="warning",
                        )
                except Exception as exc:
                    self.notify(f"Message delivery failed: {exc}", severity="error")

            self.app.run_worker(_deliver(), exclusive=False)

        self.app.push_screen(
            PromptModal(
                label=f"→ {agent_type} >",
                placeholder="message for this agent…",
            ),
            callback=on_dismiss,
        )

    def action_kill_agent(self) -> None:
        selected_agent = self._selected_agent()
        targets = [a for a in self._job.agents if a.agent_id in self._selected] or (
            [selected_agent] if selected_agent is not None else []
        )
        if not targets:
            self.notify("No agent selected", severity="warning")
            return

        running = [a for a in targets if a.status == AgentStatus.RUNNING]
        not_running = [a for a in targets if a.status != AgentStatus.RUNNING]

        for a in running:
            a.status = AgentStatus.KILLED

        if len(targets) == 1 and not running:
            # Single non-running agent — original behavior
            agent = not_running[0]
            from claude_dispatch.ui.modals.actions import ActionsModal

            def on_choice_single(result: str | None) -> None:
                if result == "v":
                    self._job.agents.remove(agent)
                    self._selected.discard(agent.agent_id)
                    self._refresh_table()
                    self.notify("Agent removed from view", severity="information")
                elif result == "h":
                    self._job.agents.remove(agent)
                    self._selected.discard(agent.agent_id)
                    self._refresh_table()
                    self.app.run_worker(
                        self._delete_agent_from_history(self._job.job_id, agent.spec.type.value),
                        exclusive=False,
                    )

            self.app.push_screen(
                ActionsModal(
                    title=f"Agent not running (status: {agent.status.value})",
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

            title = f"{len(not_running)} agent(s) not running"
            if running:
                title += f" ({len(running)} killed)"

            not_running_snapshot = list(not_running)

            def on_choice_bulk(result: str | None) -> None:
                if result == "v":
                    for a in not_running_snapshot:
                        self._job.agents.remove(a)
                        self._selected.discard(a.agent_id)
                    self._refresh_table()
                    self.notify(
                        f"{len(not_running_snapshot)} agent(s) removed from view",
                        severity="information",
                    )
                elif result == "h":
                    for a in not_running_snapshot:
                        self._job.agents.remove(a)
                        self._selected.discard(a.agent_id)
                    self._refresh_table()
                    for a in not_running_snapshot:
                        self.app.run_worker(
                            self._delete_agent_from_history(self._job.job_id, a.spec.type.value),
                            exclusive=False,
                        )

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
            self._refresh_table()
            self.notify(f"{len(running)} agent(s) killed", severity="information")

    async def _delete_agent_from_history(self, job_id: str, agent_type: str) -> None:
        from claude_dispatch.db import delete_agent_session

        try:
            await delete_agent_session(job_id, agent_type)
            self.notify("Agent removed from view and history", severity="information")
        except Exception as exc:
            self.notify(f"Failed to delete from history: {exc}", severity="error")

    def action_goto_root(self) -> None:
        self.app.pop_to_main()  # type: ignore[attr-defined]

    def action_dispatcher(self) -> None:
        self.app.open_dispatcher_conversation()  # type: ignore[attr-defined]

    def action_go_back(self) -> None:
        self.app.pop_screen()
