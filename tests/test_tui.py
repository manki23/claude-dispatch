"""TUI tests — verify screens compose and basic navigation works."""

from __future__ import annotations

import pytest
from textual.testing import AppTest

from claude_dispatch.dispatcher import DispatcherApp
from claude_dispatch.mock import make_mock_jobs, make_mock_config


@pytest.fixture
def mock_app():
    jobs = make_mock_jobs()
    config = make_mock_config()
    return DispatcherApp(jobs=jobs, config=config)


async def test_app_starts(mock_app):
    """App starts without errors and renders the jobs table."""
    async with mock_app.run_test() as pilot:
        from textual.widgets import DataTable
        table = mock_app.query_one("#jobs-table", DataTable)
        assert table.row_count == 3  # 3 mock jobs


async def test_jobs_table_has_expected_columns(mock_app):
    """Jobs table renders all expected columns."""
    async with mock_app.run_test() as pilot:
        from textual.widgets import DataTable
        table = mock_app.query_one("#jobs-table", DataTable)
        col_labels = [str(col.label) for col in table.columns.values()]
        assert "NAME" in col_labels
        assert "PHASE" in col_labels
        assert "COST" in col_labels
        assert "AGE" in col_labels


async def test_drill_into_job(mock_app):
    """Pressing Enter on a job pushes AgentsScreen."""
    async with mock_app.run_test() as pilot:
        from claude_dispatch.ui.screens.agents import AgentsScreen
        await pilot.press("enter")
        assert isinstance(mock_app.screen, AgentsScreen)


async def test_escape_from_agents_returns_to_main(mock_app):
    """Pressing Esc on AgentsScreen pops back to MainScreen."""
    async with mock_app.run_test() as pilot:
        from claude_dispatch.ui.screens.main import MainScreen
        from claude_dispatch.ui.screens.agents import AgentsScreen
        await pilot.press("enter")
        assert isinstance(mock_app.screen, AgentsScreen)
        await pilot.press("escape")
        assert isinstance(mock_app.screen, MainScreen)


async def test_help_modal_opens_and_closes(mock_app):
    """? opens HelpModal, Esc closes it."""
    async with mock_app.run_test() as pilot:
        from claude_dispatch.ui.modals.help import HelpModal
        await pilot.press("question_mark")
        assert isinstance(mock_app.screen, HelpModal)
        await pilot.press("escape")
        from claude_dispatch.ui.screens.main import MainScreen
        assert isinstance(mock_app.screen, MainScreen)


async def test_cost_modal_opens_and_closes(mock_app):
    """c opens CostModal, Esc closes it."""
    async with mock_app.run_test() as pilot:
        from claude_dispatch.ui.modals.cost import CostModal
        await pilot.press("c")
        assert isinstance(mock_app.screen, CostModal)
        await pilot.press("escape")
        from claude_dispatch.ui.screens.main import MainScreen
        assert isinstance(mock_app.screen, MainScreen)


async def test_kill_job(mock_app):
    """k on a running job marks it as killed."""
    async with mock_app.run_test() as pilot:
        from claude_dispatch.job import JobStatus
        job = mock_app.jobs[0]
        assert job.status == JobStatus.RUNNING
        await pilot.press("k")
        assert job.status == JobStatus.KILLED
