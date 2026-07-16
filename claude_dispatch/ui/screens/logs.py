"""LogsScreen — streaming output of a single Agent session."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Label, RichLog

from claude_dispatch.agent import Agent
from claude_dispatch.job import Job


class LogsScreen(Screen):
    """Full-screen log view for one agent. Press Esc to go back."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("end", "scroll_end", "Scroll to end", show=True),
    ]

    def __init__(self, job: Job, agent: Agent) -> None:
        super().__init__()
        self._job = job
        self._agent = agent

    def compose(self) -> ComposeResult:
        agent_type = self._agent.spec.type.value
        job_desc = self._job.description
        status = self._agent.status.value

        with Vertical():
            yield Label(
                f"[bold]{job_desc}[/bold] › [cyan]{agent_type}[/cyan]  "
                f"[dim]model:[/dim] {self._agent.model}  "
                f"[dim]status:[/dim] {_status_markup(status)}  "
                f"[dim]cost:[/dim] ${self._agent.cost_usd:.4f}",
                id="log-header",
            )
            yield RichLog(id="log-view", highlight=True, markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#log-view", RichLog)
        for line in self._agent.log_lines:
            log.write(line)
        # TODO: subscribe to live SDK output stream and append new lines here

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_scroll_end(self) -> None:
        self.query_one("#log-view", RichLog).scroll_end(animate=False)


def _status_markup(status: str) -> str:
    icons = {
        "running": "[green]● running[/green]",
        "done": "[dim green]✓ done[/dim green]",
        "waiting": "[dim]○ waiting[/dim]",
        "failed": "[red]✗ failed[/red]",
        "killed": "[dim red]⊘ killed[/dim red]",
    }
    return icons.get(status, status)
