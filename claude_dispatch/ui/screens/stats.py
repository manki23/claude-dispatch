"""StatsScreen — aggregate cost/time analytics from DB history."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Label, RichLog


def _render_cost_chart(daily: list[dict]) -> str:
    if not daily:
        return "[dim]No data[/dim]"
    max_cost = max(d["daily_cost"] for d in daily)
    bar_width = 20
    lines: list[str] = []
    for d in daily:
        day_label = d["day"][5:]  # "07-01"
        ratio = d["daily_cost"] / max_cost if max_cost else 0
        filled = int(ratio * bar_width)
        bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
        lines.append(f"{day_label}  {bar}  ${d['daily_cost']:.2f}")
    return "\n".join(lines)


class StatsScreen(Screen[None]):
    """Historical analytics: per-agent-type breakdown + top jobs + daily cost chart."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("tab", "next_view", "Switch", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._view: str = "agents"

    def compose(self) -> ComposeResult:
        yield Label("", id="breadcrumb")
        yield Label("", id="stats-status")

        with Vertical(id="view-agents"):
            yield Label("", id="agents-summary")
            yield DataTable(id="agents-table", cursor_type="row")

        with Vertical(id="view-jobs"):
            yield DataTable(id="jobs-table", cursor_type="row")
            yield RichLog(id="cost-chart", wrap=True)

        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#breadcrumb", Label).update(
            "[dim]DISPATCHER[/dim]  \u203a  [bold]stats[/bold]"
        )
        self.query_one("#view-jobs", Vertical).display = False
        self.query_one("#stats-status", Label).update("[dim]view:[/dim] agents")
        self.run_worker(self._load_data())

    async def _load_data(self) -> None:
        from claude_dispatch.db import (
            get_agent_type_stats,
            get_daily_cost_series,
            get_top_expensive_jobs,
        )

        agent_stats = await get_agent_type_stats()
        daily = await get_daily_cost_series(30)
        top_jobs = await get_top_expensive_jobs(10)
        self.call_from_thread(self._populate, agent_stats, daily, top_jobs)

    def _populate(
        self,
        agent_stats: list[dict],
        daily: list[dict],
        top_jobs: list[dict],
    ) -> None:
        # -- agents table --
        table = self.query_one("#agents-table", DataTable)
        table.clear(columns=True)
        table.add_columns("TYPE", "RUNS", "AVG COST", "TOTAL COST", "AVG TIME", "SUCCESS %")
        for row in agent_stats:
            avg_dur = row["avg_duration_s"] or 0
            if avg_dur < 60:
                dur_str = f"{avg_dur:.0f}s"
            else:
                dur_str = f"{avg_dur / 60:.1f}m"
            table.add_row(
                row["agent_type"],
                str(row["count"]),
                f"${row['avg_cost']:.4f}",
                f"${row['total_cost']:.4f}",
                dur_str,
                f"{row['success_pct']:.0f}%",
            )

        # -- summary --
        total_runs = sum(r["count"] for r in agent_stats)
        total_cost = sum(r["total_cost"] for r in agent_stats)
        overall_success = (
            sum(r["success_pct"] * r["count"] for r in agent_stats) / total_runs
            if total_runs
            else 0
        )
        self.query_one("#agents-summary", Label).update(
            f"[dim]total runs:[/dim] {total_runs}  "
            f"[dim]total cost:[/dim] [bold]${total_cost:.4f}[/bold]  "
            f"[dim]success:[/dim] {overall_success:.0f}%"
        )

        # -- jobs table --
        jtable = self.query_one("#jobs-table", DataTable)
        jtable.clear(columns=True)
        jtable.add_columns("DESCRIPTION", "AGENTS", "COST", "STATUS")
        for row in top_jobs:
            desc = (row["description"] or row["job_id"])[:50]
            jtable.add_row(
                desc,
                str(row["agent_count"]),
                f"${row['total_cost']:.4f}",
                row["status"] or "?",
            )

        # -- cost chart --
        chart = self.query_one("#cost-chart", RichLog)
        chart.clear()
        chart.write(_render_cost_chart(daily))

    def action_next_view(self) -> None:
        if self._view == "agents":
            self._view = "jobs"
            self.query_one("#view-agents", Vertical).display = False
            self.query_one("#view-jobs", Vertical).display = True
        else:
            self._view = "agents"
            self.query_one("#view-agents", Vertical).display = True
            self.query_one("#view-jobs", Vertical).display = False
        self.query_one("#stats-status", Label).update(f"[dim]view:[/dim] {self._view}")

    def action_refresh(self) -> None:
        table = self.query_one("#agents-table", DataTable)
        table.clear(columns=True)
        jtable = self.query_one("#jobs-table", DataTable)
        jtable.clear(columns=True)
        chart = self.query_one("#cost-chart", RichLog)
        chart.clear()
        self.run_worker(self._load_data())

    def action_go_back(self) -> None:
        self.app.pop_screen()
