"""Tests for LogsScreen live streaming behaviour."""

from __future__ import annotations

import pytest

from claude_dispatch.agent import Agent, AgentSpec, AgentStatus, AgentType
from claude_dispatch.config import Config
from claude_dispatch.dispatcher import DispatcherApp
from claude_dispatch.job import Job
from claude_dispatch.mock import make_mock_config, make_mock_jobs

# ── helpers ───────────────────────────────────────────────────────────────────


def make_agent(log_lines: list[str] | None = None) -> tuple[Job, Agent]:
    job = Job(description="test job", config=Config(), db_enabled=False)
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-code",
        status=AgentStatus.RUNNING,
    )
    agent.log_lines = list(log_lines or [])
    job.agents.append(agent)
    return job, agent


@pytest.fixture
def logs_app():
    jobs = make_mock_jobs()
    config = make_mock_config()
    return DispatcherApp(jobs=jobs, config=config), jobs[0]


# ── on_mount: existing lines rendered ────────────────────────────────────────


async def test_existing_log_lines_rendered_on_mount(logs_app) -> None:
    """Lines already in agent.log_lines appear in the RichLog on open."""
    from claude_dispatch.ui.screens.logs import LogsScreen

    app, job = logs_app
    agent = job.agents[0]
    agent.log_lines = ["line one", "line two", "line three"]

    async with app.run_test() as pilot:
        app.push_screen(LogsScreen(job=job, agent=agent))
        await pilot.pause()

        # RichLog renders to lines — just confirm the screen is a LogsScreen
        assert isinstance(app.screen, LogsScreen)
        # _rendered_count should equal number of pre-existing lines
        assert app.screen._rendered_count == 3


# ── on_mount: live callback wired ────────────────────────────────────────────


async def test_on_log_callback_replaced_on_mount(logs_app) -> None:
    """Opening LogsScreen replaces agent.on_log with a live-streaming wrapper."""
    from claude_dispatch.ui.screens.logs import LogsScreen

    app, job = logs_app
    agent = job.agents[0]
    original_callback = object()  # sentinel — not a real callable
    agent.on_log = None  # start clean

    async with app.run_test() as pilot:
        app.push_screen(LogsScreen(job=job, agent=agent))
        await pilot.pause()

        # on_log should now be the live wrapper (not None)
        assert agent.on_log is not None
        assert agent.on_log is not original_callback


async def test_prev_on_log_preserved(logs_app) -> None:
    """Existing on_log is stashed as _prev_on_log and called by the wrapper."""
    from claude_dispatch.ui.screens.logs import LogsScreen

    app, job = logs_app
    agent = job.agents[0]
    prev_calls: list[str] = []
    agent.on_log = lambda line: prev_calls.append(line)

    async with app.run_test() as pilot:
        app.push_screen(LogsScreen(job=job, agent=agent))
        await pilot.pause()

        screen = app.screen
        assert screen._prev_on_log is not None

        # Simulate a new log line arriving via the live callback
        agent.on_log("new line from SDK")
        await pilot.pause()

    # prev_on_log was called
    assert "new line from SDK" in prev_calls


# ── on_unmount: callback restored ────────────────────────────────────────────


async def test_on_log_restored_on_unmount(logs_app) -> None:
    """Closing LogsScreen restores the original agent.on_log."""
    from claude_dispatch.ui.screens.logs import LogsScreen

    app, job = logs_app
    agent = job.agents[0]
    original: list[str] = []
    agent.on_log = lambda line: original.append(line)

    async with app.run_test() as pilot:
        app.push_screen(LogsScreen(job=job, agent=agent))
        await pilot.pause()

        # on_log is the wrapper while screen is active
        wrapper = agent.on_log
        assert wrapper is not None

        await pilot.press("escape")
        await pilot.pause()

    # After pop, on_log is the original again
    assert agent.on_log is not wrapper
    # The original lambda is restored
    agent.on_log("after close")
    assert "after close" in original


async def test_on_log_none_restored_when_no_previous(logs_app) -> None:
    """If agent.on_log was None before opening, it is restored to None on close."""
    from claude_dispatch.ui.screens.logs import LogsScreen

    app, job = logs_app
    agent = job.agents[0]
    agent.on_log = None

    async with app.run_test() as pilot:
        app.push_screen(LogsScreen(job=job, agent=agent))
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert agent.on_log is None


# ── _poll_new_lines ───────────────────────────────────────────────────────────


async def test_poll_appends_new_lines(logs_app) -> None:
    """_poll_new_lines picks up lines added after mount and advances _rendered_count."""
    from claude_dispatch.ui.screens.logs import LogsScreen

    app, job = logs_app
    agent = job.agents[0]
    agent.log_lines = ["initial"]

    async with app.run_test() as pilot:
        app.push_screen(LogsScreen(job=job, agent=agent))
        await pilot.pause()

        screen = app.screen
        assert screen._rendered_count == 1

        # Simulate lines arriving after mount
        agent.log_lines.append("new line A")
        agent.log_lines.append("new line B")
        screen._poll_new_lines()

        assert screen._rendered_count == 3


async def test_poll_idempotent_when_no_new_lines(logs_app) -> None:
    """_poll_new_lines does nothing when no new lines have arrived."""
    from claude_dispatch.ui.screens.logs import LogsScreen

    app, job = logs_app
    agent = job.agents[0]
    agent.log_lines = ["a", "b"]

    async with app.run_test() as pilot:
        app.push_screen(LogsScreen(job=job, agent=agent))
        await pilot.pause()

        screen = app.screen
        count_before = screen._rendered_count
        screen._poll_new_lines()
        assert screen._rendered_count == count_before


# ── navigation ────────────────────────────────────────────────────────────────


async def test_escape_pops_logs_screen(logs_app) -> None:
    """Pressing Esc on LogsScreen pops back to AgentsScreen."""
    from claude_dispatch.ui.screens.agents import AgentsScreen
    from claude_dispatch.ui.screens.logs import LogsScreen

    app, job = logs_app

    async with app.run_test() as pilot:
        from textual.widgets import DataTable

        app.screen.query_one("#jobs-table", DataTable).focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, AgentsScreen)

        app.screen.query_one("#agents-table", DataTable).focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, LogsScreen)

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, AgentsScreen)
