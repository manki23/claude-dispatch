"""Tests for TUI action wiring: new_job, message_job, resume_job."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from claude_dispatch.dispatcher import DispatcherApp
from claude_dispatch.job import JobStatus
from claude_dispatch.mock import make_mock_config, make_mock_jobs

# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_app():
    jobs = make_mock_jobs()
    config = make_mock_config()
    return DispatcherApp(jobs=jobs, config=config)


@pytest.fixture
def empty_app():
    config = make_mock_config()
    return DispatcherApp(jobs=[], config=config)


# ── action_new_job ────────────────────────────────────────────────────────────


async def test_new_job_adds_to_jobs_list(empty_app) -> None:
    """Entering a description creates a Job and appends it to self.jobs."""
    async with empty_app.run_test() as pilot:
        screen = empty_app.screen

        # Mock push_screen_wait to return a description without real modal
        screen.app.push_screen_wait = AsyncMock(return_value="Fix the auth bug")

        # run_worker is a sync call wrapping a coroutine — mock it to avoid real SDK
        run_calls = []

        def fake_run_worker(coro, **kwargs):
            run_calls.append(coro)
            coro.close()  # prevent RuntimeWarning: coroutine never awaited
            return None

        screen.app.run_worker = fake_run_worker

        await screen.action_new_job()
        await pilot.pause()

    assert len(run_calls) == 1
    assert any(j.description == "Fix the auth bug" for j in screen.jobs)


async def test_new_job_no_description_does_nothing(empty_app) -> None:
    """Cancelling the modal (empty string) leaves jobs unchanged."""
    async with empty_app.run_test() as pilot:
        screen = empty_app.screen
        screen.app.push_screen_wait = AsyncMock(return_value="")
        screen.app.run_worker = lambda *a, **kw: None

        await screen.action_new_job()
        await pilot.pause()

    assert len(screen.jobs) == 0


async def test_new_job_creates_job_with_correct_description(empty_app) -> None:
    async with empty_app.run_test():
        screen = empty_app.screen
        screen.app.push_screen_wait = AsyncMock(return_value="Build new feature")

        def fake_run_worker(coro, **kwargs):
            coro.close()
            return None

        screen.app.run_worker = fake_run_worker

        await screen.action_new_job()

        job = next(j for j in screen.jobs if j.description == "Build new feature")
        assert job.status == JobStatus.RUNNING


# ── action_message_job ────────────────────────────────────────────────────────


async def test_message_job_calls_send_message(mock_app) -> None:
    """Typing a message calls await job.send_message(message)."""
    async with mock_app.run_test():
        screen = mock_app.screen
        job = mock_app.jobs[0]

        # Mock modal to return message
        screen.app.push_screen_wait = AsyncMock(return_value="please add logging")

        # Mock job.send_message (it's async)
        job.send_message = AsyncMock(return_value=True)

        await screen.action_message_job()

    job.send_message.assert_awaited_once_with("please add logging")


async def test_message_job_no_selection_does_nothing(empty_app) -> None:
    """No jobs in list → action_message_job is a no-op."""
    async with empty_app.run_test():
        screen = empty_app.screen
        screen.app.push_screen_wait = AsyncMock(return_value="hi")

        # Should not raise even with no jobs
        await screen.action_message_job()


async def test_message_job_empty_message_does_nothing(mock_app) -> None:
    """Cancelling the modal → send_message not called."""
    async with mock_app.run_test():
        screen = mock_app.screen
        job = mock_app.jobs[0]
        screen.app.push_screen_wait = AsyncMock(return_value="")
        job.send_message = AsyncMock(return_value=True)

        await screen.action_message_job()

    job.send_message.assert_not_awaited()


# ── action_resume_job ─────────────────────────────────────────────────────────


async def test_resume_job_already_loaded(mock_app) -> None:
    """If job_id is already in self.jobs, AgentsScreen is pushed immediately."""
    async with mock_app.run_test() as pilot:
        from claude_dispatch.ui.screens.agents import AgentsScreen

        screen = mock_app.screen
        existing_job = mock_app.jobs[0]
        screen.app.push_screen_wait = AsyncMock(return_value=existing_job.job_id)

        await screen.action_resume_job()
        await pilot.pause()

        assert isinstance(mock_app.screen, AgentsScreen)


async def test_resume_job_unknown_id_shows_notification(mock_app) -> None:
    """Unknown job_id → notify called with error severity."""
    async with mock_app.run_test():
        screen = mock_app.screen
        screen.app.push_screen_wait = AsyncMock(return_value="nonexistent-id")

        notify_calls = []
        screen.notify = lambda msg, **kw: notify_calls.append((msg, kw))

        with patch("claude_dispatch.db.list_jobs", AsyncMock(return_value=[])):
            await screen.action_resume_job()

        assert len(notify_calls) == 1
        assert "nonexistent-id" in notify_calls[0][0]
        assert notify_calls[0][1].get("severity") == "error"


async def test_resume_job_from_db_reconstructs_job(mock_app) -> None:
    """Job found in DB → Job object reconstructed and added to self.jobs."""
    async with mock_app.run_test() as pilot:
        from claude_dispatch.ui.screens.agents import AgentsScreen

        screen = mock_app.screen
        screen.app.push_screen_wait = AsyncMock(return_value="db-job-1")

        fake_jobs = [
            {
                "job_id": "db-job-1",
                "description": "Investigate flakiness",
                "status": "done",
                "cost_usd": 0.05,
            }
        ]
        fake_agents = [
            {
                "agent_type": "code",
                "session_id": "sess-abc",
                "status": "done",
                "cost_usd": 0.03,
                "created_at": "2026-01-01",
                "updated_at": "2026-01-01",
            }
        ]

        with (
            patch("claude_dispatch.db.list_jobs", AsyncMock(return_value=fake_jobs)),
            patch("claude_dispatch.db.list_agents", AsyncMock(return_value=fake_agents)),
        ):
            await screen.action_resume_job()
            await pilot.pause()

        resumed = next(j for j in screen.jobs if j.job_id == "db-job-1")
        assert resumed.description == "Investigate flakiness"
        assert resumed.status == JobStatus.DONE
        assert len(resumed.agents) == 1
        assert resumed.agents[0].session_id == "sess-abc"
        assert isinstance(mock_app.screen, AgentsScreen)


async def test_resume_job_cancelled_modal_does_nothing(mock_app) -> None:
    """Cancelling the modal (empty string) → no job added, no screen push."""
    async with mock_app.run_test():
        from claude_dispatch.ui.screens.main import MainScreen

        screen = mock_app.screen
        initial_count = len(screen.jobs)
        screen.app.push_screen_wait = AsyncMock(return_value="")

        await screen.action_resume_job()

        assert len(screen.jobs) == initial_count
        assert isinstance(mock_app.screen, MainScreen)
