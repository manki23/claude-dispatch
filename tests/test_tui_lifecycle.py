"""Tests for TUI action wiring: new_job, message_job, resume_job.

Actions now use push_screen(callback=...) instead of push_screen_wait,
so tests simulate the callback being invoked directly.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_dispatch.dispatcher import DispatcherApp
from claude_dispatch.job import JobStatus
from claude_dispatch.mock import make_mock_config, make_mock_jobs


# ── helpers ───────────────────────────────────────────────────────────────────


def make_push_screen_stub(return_value, passthrough=None):
    """Return a push_screen replacement that immediately calls callback(return_value).

    If passthrough is provided, non-callback calls (real screen pushes) are
    forwarded to it so AgentsScreen etc. actually land on the stack.
    """

    def stub(screen, callback=None, **kw):
        if callback:
            callback(return_value)
        elif passthrough is not None:
            passthrough(screen, **kw)

    return stub


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

        run_calls = []

        def fake_run_worker(coro, **kwargs):
            run_calls.append(coro)
            if hasattr(coro, "close"):
                coro.close()
            return None

        screen.app.push_screen = make_push_screen_stub("Fix the auth bug")
        screen.app.run_worker = fake_run_worker

        screen.action_new_job()
        await pilot.pause()

    assert len(run_calls) == 1
    assert any(j.description == "Fix the auth bug" for j in screen.jobs)


async def test_new_job_no_description_does_nothing(empty_app) -> None:
    """Cancelling the modal (None) leaves jobs unchanged."""
    async with empty_app.run_test() as pilot:
        screen = empty_app.screen
        screen.app.push_screen = make_push_screen_stub(None)
        screen.app.run_worker = lambda *a, **kw: None

        screen.action_new_job()
        await pilot.pause()

    assert len(screen.jobs) == 0


async def test_new_job_creates_job_with_correct_description(empty_app) -> None:
    async with empty_app.run_test():
        screen = empty_app.screen
        screen.app.push_screen = make_push_screen_stub("Build new feature")

        def fake_run_worker(coro, **kwargs):
            if hasattr(coro, "close"):
                coro.close()
            return None

        screen.app.run_worker = fake_run_worker
        screen.action_new_job()

        job = next(j for j in screen.jobs if j.description == "Build new feature")
        assert job.status == JobStatus.RUNNING


async def test_new_job_stores_full_instructions(empty_app) -> None:
    """Instructions are stored on the job and description is separate short name."""
    async with empty_app.run_test():
        screen = empty_app.screen
        call_count = [0]

        def two_step_push(modal, callback=None, **kw):
            call_count[0] += 1
            if callback:
                if call_count[0] == 1:
                    # Step 1: return full instructions
                    callback("Fix the auth bug in services/auth/handler.py line 42")
                else:
                    # Step 2: return a short name
                    callback("Fix auth bug")

        screen.app.push_screen = two_step_push

        def fake_run_worker(coro, **kwargs):
            if hasattr(coro, "close"):
                coro.close()

        screen.app.run_worker = fake_run_worker
        screen.action_new_job()

    job = screen.jobs[-1]
    assert job.description == "Fix auth bug"
    assert job.instructions == "Fix the auth bug in services/auth/handler.py line 42"


async def test_new_job_blank_name_uses_truncated_instructions(empty_app) -> None:
    """Blank name (step 2 empty/None) → description auto-truncated from instructions."""
    async with empty_app.run_test():
        screen = empty_app.screen
        call_count = [0]
        long_instructions = "A" * 80

        def two_step_push(modal, callback=None, **kw):
            call_count[0] += 1
            if callback:
                if call_count[0] == 1:
                    callback(long_instructions)
                else:
                    callback(None)  # Esc on step 2

        screen.app.push_screen = two_step_push

        def fake_run_worker(coro, **kwargs):
            if hasattr(coro, "close"):
                coro.close()

        screen.app.run_worker = fake_run_worker
        screen.action_new_job()

    job = screen.jobs[-1]
    assert job.description == long_instructions[:60]
    assert job.instructions == long_instructions


# ── action_message_job ────────────────────────────────────────────────────────


async def test_message_job_calls_send_message(mock_app) -> None:
    """Typing a message queues run_worker(job.send_message(...))."""
    async with mock_app.run_test():
        screen = mock_app.screen
        job = mock_app.jobs[0]

        screen.app.push_screen = make_push_screen_stub("please add logging")

        worker_coroutines = []

        def fake_run_worker(coro, **kwargs):
            worker_coroutines.append(coro)
            if hasattr(coro, "close"):
                coro.close()
            return None

        screen.app.run_worker = fake_run_worker
        screen.action_message_job()

    assert len(worker_coroutines) == 1


async def test_message_job_no_selection_notifies(empty_app) -> None:
    """No jobs in list → notification shown, push_screen not called."""
    async with empty_app.run_test():
        screen = empty_app.screen
        push_called = []
        screen.app.push_screen = lambda *a, **kw: push_called.append(True)

        notified = []
        screen.notify = lambda msg, **kw: notified.append(msg)

        screen.action_message_job()

    assert push_called == []
    assert any("No job" in n for n in notified)


async def test_message_job_empty_message_does_nothing(mock_app) -> None:
    """Cancelling the modal (None) → run_worker not called."""
    async with mock_app.run_test():
        screen = mock_app.screen
        screen.app.push_screen = make_push_screen_stub(None)

        worker_calls = []
        screen.app.run_worker = lambda *a, **kw: worker_calls.append(True)

        screen.action_message_job()

    assert worker_calls == []


# ── action_resume_job ─────────────────────────────────────────────────────────


async def test_resume_job_already_loaded(mock_app) -> None:
    """If job_id is already in self.jobs, AgentsScreen is pushed."""
    async with mock_app.run_test() as pilot:
        from claude_dispatch.ui.screens.agents import AgentsScreen

        screen = mock_app.screen
        existing_job = mock_app.jobs[0]
        real_push = screen.app.push_screen
        screen.app.push_screen = make_push_screen_stub(existing_job.job_id, passthrough=real_push)

        # _do_resume is run in a worker; schedule it directly on the event loop
        def run_worker_direct(coro, **kw):
            asyncio.ensure_future(coro)

        screen.app.run_worker = run_worker_direct

        screen.action_resume_job()
        await pilot.pause(0.2)

        assert isinstance(mock_app.screen, AgentsScreen)


async def test_resume_job_unknown_id_shows_notification(mock_app) -> None:
    """Unknown job_id → notify called with error severity."""
    async with mock_app.run_test() as pilot:
        screen = mock_app.screen
        screen.app.push_screen = make_push_screen_stub("nonexistent-id")

        notify_calls = []
        screen.notify = lambda msg, **kw: notify_calls.append((msg, kw))

        def run_worker_direct(coro, **kw):
            asyncio.ensure_future(coro)

        screen.app.run_worker = run_worker_direct

        with patch("claude_dispatch.db.list_jobs", AsyncMock(return_value=[])):
            screen.action_resume_job()
            await pilot.pause(0.2)

    assert any("nonexistent-id" in c[0] for c in notify_calls)


async def test_resume_job_from_db_reconstructs_job(mock_app) -> None:
    """Job found in DB → Job object reconstructed and added to self.jobs."""
    async with mock_app.run_test() as pilot:
        from claude_dispatch.ui.screens.agents import AgentsScreen

        screen = mock_app.screen
        real_push = screen.app.push_screen
        screen.app.push_screen = make_push_screen_stub("db-job-1", passthrough=real_push)

        def run_worker_direct(coro, **kw):
            asyncio.ensure_future(coro)

        screen.app.run_worker = run_worker_direct

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
            screen.action_resume_job()
            await pilot.pause(0.2)

        resumed = next(j for j in screen.jobs if j.job_id == "db-job-1")
        assert resumed.description == "Investigate flakiness"
        assert resumed.status == JobStatus.DONE
        assert len(resumed.agents) == 1
        assert resumed.agents[0].session_id == "sess-abc"
        assert isinstance(mock_app.screen, AgentsScreen)


async def test_resume_job_cancelled_modal_does_nothing(mock_app) -> None:
    """Cancelling the modal (None) → no job added, no screen push."""
    async with mock_app.run_test():
        from claude_dispatch.ui.screens.main import MainScreen

        screen = mock_app.screen
        initial_count = len(screen.jobs)
        screen.app.push_screen = make_push_screen_stub(None)

        worker_calls = []
        screen.app.run_worker = lambda *a, **kw: worker_calls.append(True)

        screen.action_resume_job()

        assert len(screen.jobs) == initial_count
        assert worker_calls == []
        assert isinstance(mock_app.screen, MainScreen)
