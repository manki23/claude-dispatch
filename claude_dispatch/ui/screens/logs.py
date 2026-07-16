"""LogsScreen — streaming output of a single Agent session."""

from __future__ import annotations

from collections.abc import Callable

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
        self._rendered_count: int = 0
        self._prev_on_log: Callable[[str], None] | None = None

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

        # Render lines that already exist
        for line in self._agent.log_lines:
            log.write(line)
        self._rendered_count = len(self._agent.log_lines)

        # Direct callback: write new lines immediately as they arrive
        self._prev_on_log = self._agent.on_log

        def _live_write(line: str) -> None:
            if self._prev_on_log:
                self._prev_on_log(line)
            self._append_line(line)

        self._agent.on_log = _live_write

        # Poll fallback: catch any lines that slipped in before callback was attached
        self.set_interval(0.5, self._poll_new_lines)

    def on_unmount(self) -> None:
        # Restore the original on_log so other observers (CLI, etc.) still work
        self._agent.on_log = self._prev_on_log

    # ── internal helpers ───────────────────────────────────────────

    def _append_line(self, line: str) -> None:
        """Write one line to the RichLog and auto-scroll if already at bottom."""
        log = self.query_one("#log-view", RichLog)
        at_bottom = log.scroll_y >= log.virtual_size.height - log.size.height - 1
        log.write(line)
        if at_bottom:
            log.scroll_end(animate=False)

    def _poll_new_lines(self) -> None:
        """Append any log_lines that arrived before the live callback was wired."""
        new_lines = self._agent.log_lines[self._rendered_count :]
        for line in new_lines:
            self._append_line(line)
        self._rendered_count += len(new_lines)

    # ── actions ───────────────────────────────────────────────────

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
