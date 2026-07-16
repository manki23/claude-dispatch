"""Dispatcher — the Textual TUI application (control plane)."""

from __future__ import annotations

from pathlib import Path

from textual.app import App
from textual.worker import Worker, WorkerState

from claude_dispatch.agent import Agent, AgentSpec, AgentType
from claude_dispatch.config import Config, load_config
from claude_dispatch.job import Job


class DispatcherApp(App):
    """k9s-style TUI for orchestrating parallel Claude Code sessions."""

    TITLE = "claude-dispatch"
    CSS_PATH = Path(__file__).parent / "app.tcss"

    def __init__(self, jobs: list[Job] | None = None, config: Config | None = None) -> None:
        super().__init__()
        self.config = config or load_config()
        self.jobs: list[Job] = jobs or []
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
        self.push_screen(MainScreen(jobs=self.jobs))
