"""AgentsScreen — list of agents inside a Job."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Label

from claude_dispatch.agent import Agent, AgentStatus
from claude_dispatch.job import Job

_STATUS_ICONS: dict[str, str] = {
    AgentStatus.RUNNING: "[green]● running[/green]",
    AgentStatus.DONE: "[dim green]✓ done[/dim green]",
    AgentStatus.WAITING: "[dim]○ waiting[/dim]",
    AgentStatus.FAILED: "[red]✗ failed[/red]",
    AgentStatus.KILLED: "[dim red]⊘ killed[/dim red]",
}


class AgentsScreen(Screen):
    """Drill-in view: agents for one Job. Enter → logs. Esc → back."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("k", "kill_agent", "Kill agent", show=True),
    ]

    def __init__(self, job: Job) -> None:
        super().__init__()
        self._job = job

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(
                f"[dim]Jobs[/dim] › [bold]{self._job.description}[/bold]  "
                f"[dim]phase:[/dim] {self._job.phase.value}  "
                f"[dim]cost:[/dim] ${self._job.cost_usd:.4f}",
                id="agents-header",
            )
            yield DataTable(id="agents-table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#agents-table", DataTable)
        table.add_columns("TYPE", "MODEL", "STATUS", "COST", "LAST ACTION")
        self._refresh_table()
        self.set_interval(1.0, self._refresh_table)

    def _refresh_table(self) -> None:
        table = self.query_one("#agents-table", DataTable)
        cursor_row = table.cursor_row
        table.clear()
        for agent in self._job.agents:
            table.add_row(
                agent.spec.type.value,
                agent.model,
                _STATUS_ICONS.get(agent.status, agent.status.value),
                f"${agent.cost_usd:.4f}",
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

    def action_view_logs(self) -> None:
        agent = self._selected_agent()
        if agent:
            from claude_dispatch.ui.screens.logs import LogsScreen

            self.app.push_screen(LogsScreen(job=self._job, agent=agent))

    def action_kill_agent(self) -> None:
        agent = self._selected_agent()
        if agent and agent.status == AgentStatus.RUNNING:
            agent.status = AgentStatus.KILLED
            self._refresh_table()

    def action_go_back(self) -> None:
        self.app.pop_screen()
