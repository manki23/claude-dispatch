"""LogsScreen — streaming output of a single Agent session."""

from __future__ import annotations

import platform
import subprocess
from collections.abc import Callable
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Label, RichLog

from claude_dispatch.agent import Agent
from claude_dispatch.job import Job


class LogsScreen(Screen[None]):
    """Full-screen log view for one agent. Press Esc to go back."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("ctrl+1", "goto_root", "Dispatcher", show=False),
        Binding("ctrl+2", "goto_job", "Job", show=False),
        Binding("d", "dispatcher", "Chat", show=True),
        Binding("end", "scroll_end", "Scroll to end", show=True),
        Binding("ctrl+y", "copy_log", "Copy log", show=True),
    ]

    def __init__(self, job: Job, agent: Agent) -> None:
        super().__init__()
        self._job = job
        self._agent = agent
        self._rendered_count: int = 0
        self._prev_on_log: Callable[[str], None] | None = None

    def compose(self) -> ComposeResult:
        status = self._agent.status.value

        with Vertical():
            yield Label("", id="breadcrumb")
            yield Label(
                f"[dim]model:[/dim] {self._agent.model}  "
                f"[dim]status:[/dim] {_status_markup(status)}  "
                f"[dim]cost:[/dim] ${self._agent.cost_usd:.4f}",
                id="log-header",
            )
            yield RichLog(id="log-view", highlight=True, markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#breadcrumb", Label).update(
            f"[dim]<ctrl+1>[/dim] [dim]DISPATCHER[/dim]  ›  "
            f"[dim]<ctrl+2>[/dim] [dim]{self._job.description[:35]}[/dim]  ›  "
            f"[bold]{self._agent.spec.type.value} logs[/bold]"
        )
        log = self.query_one("#log-view", RichLog)

        # Render existing lines — from log file (subprocess) or in-memory list
        if self._agent.log_path:
            lp = Path(self._agent.log_path)
            initial_lines = lp.read_text().splitlines() if lp.exists() else []
        else:
            initial_lines = self._agent.log_lines
        for line in initial_lines:
            log.write(line)
        self._rendered_count = len(initial_lines)

        # Direct callback: write new lines immediately as they arrive
        self._prev_on_log = self._agent.on_log

        def _live_write(line: str) -> None:
            if self._prev_on_log:
                self._prev_on_log(line)
            self._append_line(line)

        self._agent.on_log = _live_write

        # Poll fallback: catch any lines that slipped in before callback was attached
        self.set_interval(0.5, self._poll_new_lines)
        # Refresh header so status/cost stay current
        self.set_interval(1.0, self._refresh_header)

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

    def _refresh_header(self) -> None:
        """Keep header status/cost in sync with the live agent."""
        self.query_one("#log-header", Label).update(
            f"[dim]model:[/dim] {self._agent.model}  "
            f"[dim]status:[/dim] {_status_markup(self._agent.status.value)}  "
            f"[dim]cost:[/dim] ${self._agent.cost_usd:.4f}"
        )

    def _poll_new_lines(self) -> None:
        """Append new log lines — from file (subprocess agent) or in-memory list."""
        if self._agent.log_path:
            lp = Path(self._agent.log_path)
            if lp.exists():
                all_lines = lp.read_text().splitlines()
                new_lines = all_lines[self._rendered_count :]
                for line in new_lines:
                    self._append_line(line)
                self._rendered_count += len(new_lines)
        else:
            new_lines = self._agent.log_lines[self._rendered_count :]
            for line in new_lines:
                self._append_line(line)
            self._rendered_count += len(new_lines)

    # ── actions ───────────────────────────────────────────────────

    def action_copy_log(self) -> None:
        """Copy all log lines to the system clipboard."""
        lines = self._agent.log_lines[:]
        if self._agent.log_path:
            lp = Path(self._agent.log_path)
            if lp.exists():
                lines = lp.read_text().splitlines()
        text = "\n".join(lines)
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.run(["pbcopy"], input=text.encode(), check=True)
            elif system == "Linux":
                subprocess.run(
                    ["xclip", "-selection", "clipboard"], input=text.encode(), check=True
                )
            elif system == "Windows":
                subprocess.run(["clip"], input=text.encode(), check=True)
            self.notify("Log copied to clipboard", timeout=2)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            self.notify(f"Copy failed: {exc}", severity="error", timeout=3)

    def action_goto_root(self) -> None:
        self.app.pop_to_main()  # type: ignore[attr-defined]

    def action_goto_job(self) -> None:
        self.app.pop_to_agents()  # type: ignore[attr-defined]

    def action_dispatcher(self) -> None:
        self.app.open_dispatcher_conversation()  # type: ignore[attr-defined]

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
