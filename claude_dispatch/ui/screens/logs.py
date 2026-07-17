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
from claude_dispatch.ui.screens.agents import agent_status_markup
from claude_dispatch.ui.widgets.dispatch_header import DispatchHeader, key_hint

_KEY_HINTS = (
    f"  {key_hint('esc')}  Back          {key_hint('d')}  Chat\n"
    f"  {key_hint('a')}  Autoscroll     {key_hint('w')}  Wrap\n"
    f"  {key_hint('f')}  Fullscreen     {key_hint('end')}  Scroll end\n"
    f"  {key_hint('ctrl+y')}  Copy log"
)


class LogsScreen(Screen[None]):
    """Full-screen log view for one agent. Press Esc to go back."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("1", "goto_root", "Dispatcher", show=False),
        Binding("2", "goto_job", "Job", show=False),
        Binding("d", "dispatcher", "Chat", show=True),
        Binding("a", "toggle_autoscroll", "Autoscroll", show=True),
        Binding("w", "toggle_wrap", "Wrap", show=True),
        Binding("f", "toggle_fullscreen", "Fullscreen", show=True),
        Binding("end", "scroll_end", "Scroll to end", show=True),
        Binding("ctrl+y", "copy_log", "Copy log", show=True),
    ]

    def __init__(self, job: Job, agent: Agent) -> None:
        super().__init__()
        self._job = job
        self._agent = agent
        self._rendered_count: int = 0
        self._prev_on_log: Callable[[str], None] | None = None
        self._autoscroll: bool = True
        self._fullscreen: bool = False
        self._header: DispatchHeader | None = None

    def compose(self) -> ComposeResult:
        status = self._agent.status.value
        self._header = DispatchHeader(_KEY_HINTS)
        yield self._header
        with Vertical():
            yield Label("", id="breadcrumb")
            yield Label(
                f"[dim]model:[/dim] {self._agent.model}  "
                f"[dim]status:[/dim] {agent_status_markup(status)}  "
                f"[dim]cost:[/dim] ${self._agent.cost_usd:.4f}",
                id="log-header",
            )
            yield RichLog(id="log-view", highlight=True, markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#breadcrumb", Label).update(
            f"[dim][1][/dim] [dim]DISPATCHER[/dim]  ›  "
            f"[dim][2][/dim] [dim]{self._job.description[:35]}[/dim]  ›  "
            f"[bold]{self._agent.spec.type.value} logs[/bold]"
        )
        self.query_one("#log-view", RichLog).focus()
        log = self.query_one("#log-view", RichLog)

        # Render existing lines — from log file (subprocess) or in-memory list
        if self._agent.log_path:
            lp = Path(self._agent.log_path)
            try:
                initial_lines = lp.read_text().splitlines() if lp.exists() else []
            except OSError:
                initial_lines = []
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
            self._rendered_count += 1  # prevent _poll_new_lines from re-rendering this line

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
        """Write one line to the RichLog and auto-scroll if flag is set."""
        log = self.query_one("#log-view", RichLog)
        log.write(line)
        if self._autoscroll:
            log.scroll_end(animate=False)

    def _refresh_header(self) -> None:
        """Keep header status/cost in sync with the live agent."""
        scroll_indicator = "[green]on[/green]" if self._autoscroll else "[dim red]off[/dim red]"
        self.query_one("#log-header", Label).update(
            f"[dim]model:[/dim] {self._agent.model}  "
            f"[dim]status:[/dim] {agent_status_markup(self._agent.status.value)}  "
            f"[dim]cost:[/dim] ${self._agent.cost_usd:.4f}  "
            f"[dim]auto-scroll:[/dim] {scroll_indicator}"
        )

    def _poll_new_lines(self) -> None:
        """Append new log lines — from file (subprocess agent) or in-memory list."""
        if self._agent.log_path:
            lp = Path(self._agent.log_path)
            if lp.exists():
                try:
                    all_lines = lp.read_text().splitlines()
                except OSError:
                    return
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

    def action_toggle_autoscroll(self) -> None:
        self._autoscroll = not self._autoscroll
        self._refresh_header()
        if self._autoscroll:
            self.query_one("#log-view", RichLog).scroll_end(animate=False)

    def action_toggle_wrap(self) -> None:
        log = self.query_one("#log-view", RichLog)
        log.wrap = not log.wrap

    def action_toggle_fullscreen(self) -> None:
        self._fullscreen = not self._fullscreen
        show = not self._fullscreen
        self.query_one("#breadcrumb", Label).display = show
        self.query_one("#log-header", Label).display = show
        self.query_one(Footer).display = show
        if self._header is not None:
            self._header.display = show

    def action_copy_log(self) -> None:
        """Copy all log lines to the system clipboard."""
        lines = self._agent.log_lines[:]
        if self._agent.log_path:
            lp = Path(self._agent.log_path)
            if lp.exists():
                try:
                    lines = lp.read_text().splitlines()
                except OSError:
                    pass
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
        except FileNotFoundError:
            self.notify("Clipboard tool not found (pbcopy/xclip/clip)", severity="error")
        except subprocess.CalledProcessError as exc:
            self.notify(f"Copy failed: {exc}", severity="error")

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
