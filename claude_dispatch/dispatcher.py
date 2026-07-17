"""Dispatcher — the Textual TUI application (control plane)."""

from __future__ import annotations

import os
from pathlib import Path

from textual.app import App
from textual.worker import Worker, WorkerState

from claude_dispatch.agent import Agent, AgentSpec, AgentStatus, AgentType
from claude_dispatch.config import Config, load_config
from claude_dispatch.job import Job


async def _load_jobs_from_db(config: Config) -> list[Job]:
    """Reconstruct Job+Agent objects from the DB for all previously-run jobs."""
    from claude_dispatch.agent import AgentSpec, AgentType
    from claude_dispatch.db import list_agents, list_jobs
    from claude_dispatch.job import Job, JobStatus

    job_rows = await list_jobs()
    jobs: list[Job] = []

    for row in job_rows:
        try:
            job_status = JobStatus(row["status"])
        except (ValueError, TypeError):
            job_status = JobStatus.DONE

        job = Job(
            description=row["description"] or "",
            instructions=row.get("instructions") or "",
            config=config,
            job_id=row["job_id"],
            status=job_status,
            db_enabled=True,
        )

        agent_rows = await list_agents(row["job_id"])
        for ar in agent_rows:
            try:
                agent_type = AgentType(ar["agent_type"])
            except ValueError:
                continue
            try:
                agent_status = AgentStatus(ar["status"])
            except (ValueError, TypeError):
                agent_status = AgentStatus.DONE

            # If PID is stored, check if process is actually still alive
            pid = ar.get("pid")
            if agent_status == AgentStatus.RUNNING and pid:
                try:
                    os.kill(pid, 0)  # signal 0 — checks existence only
                except (ProcessLookupError, PermissionError):
                    agent_status = AgentStatus.FAILED  # process is gone

            agent = Agent(
                spec=AgentSpec(type=agent_type),
                job_id=row["job_id"],
                agent_id=f"{row['job_id']}-{ar['agent_type']}",
                status=agent_status,
                session_id=ar["session_id"],
                cost_usd=ar["cost_usd"] or 0.0,
                log_path=ar.get("log_path"),
            )
            # Populate in-memory log lines from log file (if available)
            if agent.log_path:
                lp = Path(agent.log_path)
                if lp.exists():
                    agent.log_lines = lp.read_text().splitlines()

            job.agents.append(agent)

        jobs.append(job)

    return jobs


class DispatcherApp(App[None]):
    """k9s-style TUI for orchestrating parallel Claude Code sessions."""

    TITLE = "claude-dispatch"
    CSS_PATH = Path(__file__).parent / "app.tcss"

    def __init__(self, jobs: list[Job] | None = None, config: Config | None = None) -> None:
        super().__init__()
        self.config = config or load_config()
        self._explicit_jobs = jobs  # None = not provided → load from DB on mount
        self.jobs: list[Job] = jobs if jobs is not None else []
        # Singleton dispatcher agent — created once, resumed across opens via session_id.
        self._dispatcher_agent: Agent = Agent(
            spec=AgentSpec(type=AgentType.DISPATCHER),
            job_id="dispatcher",
            agent_id="dispatcher-0",
        )
        self._dispatcher_agent.get_or_create_conversation()

    def open_dispatcher_conversation(self) -> None:
        """Push ConversationScreen for the dispatcher agent with live context."""
        from claude_dispatch.dispatcher_context import build_dispatcher_system_prompt
        from claude_dispatch.ui.screens.conversation import ConversationScreen

        # Dummy Job wrapper so ConversationScreen has a description to show.
        dummy_job = Job(
            description="dispatcher",
            config=self.config,
            job_id="dispatcher",
            db_enabled=False,
        )
        self.push_screen(
            ConversationScreen(
                job=dummy_job,
                agent=self._dispatcher_agent,
                system_prompt_factory=lambda: build_dispatcher_system_prompt(self.jobs),
            )
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Catch any worker (job) failure and surface it as a notification.

        Without this, an unhandled exception in a background worker crashes
        the entire TUI.
        """
        if event.state == WorkerState.ERROR:
            exc = event.worker.error
            msg = f"{type(exc).__name__}: {exc}" if exc else "unknown error"
            self.notify(msg, severity="error", title="Job failed")

    async def on_mount(self) -> None:
        from claude_dispatch.db import init_db
        from claude_dispatch.ui.screens.main import MainScreen

        await init_db()

        # Load previously-run jobs from DB only when no jobs were explicitly provided
        # (jobs=None → production start; jobs=[] → test with explicit empty list)
        if self._explicit_jobs is None:
            self.jobs = await _load_jobs_from_db(self.config)

        self.push_screen(MainScreen(jobs=self.jobs))
