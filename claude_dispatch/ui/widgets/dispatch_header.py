"""DispatchHeader — persistent k9s-style header shared across all screens."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Label

# ASCII logo — pyfiglet "small" font. Lines ending with \ get a trailing space
# before [/cyan] to avoid Rich treating \[ as an escaped bracket.
_LOGO = (
    "[cyan] ___ ___ ___ ___  _ _____ ___ _  _ ___ ___ [/cyan]\n"
    "[cyan]|   \\_ _/ __| _ \\/_\\_   _/ __| || | __| _ \\ [/cyan]\n"
    "[cyan]| |) | |\\__ \\  _/ _ \\| || (__| __ | _||   /[/cyan]\n"
    "[cyan]|___/___|___/_|/_/ \\_\\_| \\___|_||_|___|_|_\\ [/cyan]"
)


def key_hint(k: str) -> str:
    """Format a key name as a k9s-style dim-bracketed hint."""
    return f"[dim]<[/dim][bold]{k}[/bold][dim]>[/dim]"


class DispatchHeader(Widget):
    """k9s-style 5-line header: live context | per-screen key hints | logo.

    Refreshes version/jobs/cost every second from ``app.jobs``.
    Pass per-screen key hints as a string to the constructor.
    """

    DEFAULT_CSS = """
    DispatchHeader {
        height: 5;
    }
    """

    def __init__(self, key_hints: str) -> None:
        super().__init__()
        self._key_hints = key_hints

    def compose(self) -> ComposeResult:
        with Horizontal(id="dispatch-header"):
            yield Label("", id="header-context")
            yield Label(self._key_hints, id="header-keys")
            yield Label(_LOGO, id="header-logo")

    def on_mount(self) -> None:
        self._refresh()
        self.set_interval(1.0, self._refresh)

    def _refresh(self) -> None:
        jobs: list = getattr(self.app, "jobs", [])
        running = sum(1 for j in jobs if getattr(j.status, "value", str(j.status)) == "running")
        total_jobs = len(jobs)
        total_cost = sum(j.cost_usd for j in jobs)
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
