"""Tests for AgentsScreen `m` binding and Job.on_agent_ready callback."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from claude_dispatch.agent import Agent, AgentSpec, AgentStatus, AgentType
from claude_dispatch.config import Config
from claude_dispatch.dispatcher import DispatcherApp
from claude_dispatch.job import Job
from claude_dispatch.mock import make_mock_config, make_mock_jobs

# ── helpers ───────────────────────────────────────────────────────────────────


def make_job_with_agent(
    agent_type: AgentType = AgentType.CODE,
    status: AgentStatus = AgentStatus.RUNNING,
) -> Job:
    job = Job(description="test", config=Config(), db_enabled=False)
    agent = Agent(
        spec=AgentSpec(type=agent_type, cwd="/tmp"),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-{agent_type.value}",
        status=status,
    )
    job.agents.append(agent)
    return job


# ── Job.on_agent_ready ────────────────────────────────────────────────────────


def test_on_agent_ready_called_for_plan_agent(tmp_path) -> None:
    """on_agent_ready fires for the plan agent created in _run_plan_phase."""
    import asyncio
    from unittest.mock import patch

    import yaml
    from claude_code_sdk.types import ResultMessage

    job = Job(description="test", config=Config(), db_enabled=False)
    job._workdir = tmp_path

    ready_agents: list[str] = []
    job.on_agent_ready = lambda a: ready_agents.append(a.spec.type.value)

    def fake_result():
        return ResultMessage(
            subtype="result",
            duration_ms=10,
            duration_api_ms=5,
            is_error=False,
            num_turns=1,
            session_id="s1",
            total_cost_usd=0.001,
        )

    async def fake_query(prompt, options):
        (tmp_path / "job-plan.yaml").write_text(yaml.dump({"summary": "s", "agents": []}))
        yield fake_result()

    with patch("claude_dispatch.agent.query", fake_query):
        asyncio.run(job._run_plan_phase())

    assert "plan" in ready_agents


def test_on_agent_ready_called_for_exec_agents(tmp_path) -> None:
    """on_agent_ready fires for each execution agent."""
    import asyncio

    import yaml
    from claude_code_sdk.types import ResultMessage

    plan = {
        "summary": "s",
        "agents": [
            {"type": "code", "cwd": str(tmp_path)},
            {"type": "jira"},
        ],
    }
    (tmp_path / "job-plan.yaml").write_text(yaml.dump(plan))

    job = Job(description="test", config=Config(), db_enabled=False)
    job._workdir = tmp_path

    ready_types: list[str] = []
    job.on_agent_ready = lambda a: ready_types.append(a.spec.type.value)

    def fake_result():
        return ResultMessage(
            subtype="result",
            duration_ms=10,
            duration_api_ms=5,
            is_error=False,
            num_turns=1,
            session_id="s1",
            total_cost_usd=0.001,
        )

    async def fake_query(prompt, options):
        yield fake_result()

    with patch("claude_dispatch.agent.query", fake_query):
        asyncio.run(job._run_execute_phase())

    assert "code" in ready_types
    assert "jira" in ready_types


def test_on_agent_ready_log_callback_fires(tmp_path) -> None:
    """Log lines emitted during a turn reach the on_agent_ready-attached callback."""
    import asyncio

    import yaml
    from claude_code_sdk.types import AssistantMessage, ResultMessage, TextBlock

    (tmp_path / "job-plan.yaml").write_text(yaml.dump({"summary": "s", "agents": []}))

    job = Job(description="test", config=Config(), db_enabled=False)
    job._workdir = tmp_path

    captured_logs: list[str] = []

    def _on_ready(agent) -> None:
        agent.on_log = lambda line: captured_logs.append(line)

    job.on_agent_ready = _on_ready

    def fake_result():
        return ResultMessage(
            subtype="result",
            duration_ms=10,
            duration_api_ms=5,
            is_error=False,
            num_turns=1,
            session_id="s1",
            total_cost_usd=0.001,
        )

    async def fake_query(prompt, options):
        (tmp_path / "job-plan.yaml").write_text(yaml.dump({"summary": "s", "agents": []}))
        yield AssistantMessage(content=[TextBlock(text="planning done")], model="claude-haiku-4-5")
        yield fake_result()

    with patch("claude_dispatch.agent.query", fake_query):
        asyncio.run(job._run_plan_phase())

    assert any("planning done" in line for line in captured_logs)


def test_no_on_agent_ready_does_not_crash(tmp_path) -> None:
    """on_agent_ready=None (default) → no error."""
    import asyncio

    import yaml
    from claude_code_sdk.types import ResultMessage

    job = Job(description="test", config=Config(), db_enabled=False)
    job._workdir = tmp_path
    assert job.on_agent_ready is None

    async def fake_query(prompt, options):
        (tmp_path / "job-plan.yaml").write_text(yaml.dump({"summary": "s", "agents": []}))
        yield ResultMessage(
            subtype="result",
            duration_ms=10,
            duration_api_ms=5,
            is_error=False,
            num_turns=1,
            session_id="s1",
            total_cost_usd=0.001,
        )

    with patch("claude_dispatch.agent.query", fake_query):
        asyncio.run(job._run_plan_phase())  # must not raise


# ── AgentsScreen: `m` binding ─────────────────────────────────────────────────


@pytest.fixture
def agents_app():
    jobs = make_mock_jobs()
    config = make_mock_config()
    app = DispatcherApp(jobs=jobs, config=config)
    return app, jobs[0]


async def test_message_agent_calls_send_message(agents_app) -> None:
    """m on AgentsScreen calls await job.send_message(message, agent_type=...)."""
    import asyncio

    app, job = agents_app

    async with app.run_test() as pilot:
        from claude_dispatch.ui.screens.agents import AgentsScreen

        app.screen.query_one("#jobs-table").focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, AgentsScreen)

        screen = app.screen
        agent = job.agents[0]

        screen.app.push_screen = lambda s, callback=None, **kw: (
            callback and callback("add more context")
        )
        job.send_message = AsyncMock(return_value=True)

        worker_coros = []

        def fake_run_worker(coro, **kw):
            worker_coros.append(coro)
            asyncio.ensure_future(coro)

        screen.app.run_worker = fake_run_worker

        screen.action_message_agent()
        await pilot.pause(0.2)

        job.send_message.assert_awaited_once_with("add more context", agent_id=agent.agent_id)


async def test_message_agent_empty_message_no_call(agents_app) -> None:
    """Cancelling the modal → send_message not called."""
    app, job = agents_app

    async with app.run_test() as pilot:
        app.screen.query_one("#jobs-table").focus()
        await pilot.press("enter")
        await pilot.pause()

        screen = app.screen
        screen.app.push_screen = lambda s, callback=None, **kw: callback and callback(None)
        job.send_message = AsyncMock(return_value=True)

        worker_calls = []
        screen.app.run_worker = lambda *a, **kw: worker_calls.append(True)

        screen.action_message_agent()

        job.send_message.assert_not_awaited()
        assert worker_calls == []


async def test_message_agent_delivery_failure_shows_notification(agents_app) -> None:
    """send_message returns False → notify with warning severity."""
    import asyncio

    app, job = agents_app

    async with app.run_test() as pilot:
        app.screen.query_one("#jobs-table").focus()
        await pilot.press("enter")
        await pilot.pause()

        screen = app.screen
        screen.app.push_screen = lambda s, callback=None, **kw: callback and callback("hello")
        job.send_message = AsyncMock(return_value=False)

        notify_calls = []
        screen.notify = lambda msg, **kw: notify_calls.append((msg, kw))

        def fake_run_worker(coro, **kw):
            asyncio.ensure_future(coro)

        screen.app.run_worker = fake_run_worker

        screen.action_message_agent()
        await pilot.pause(0.2)

        assert len(notify_calls) == 1
        assert notify_calls[0][1].get("severity") == "warning"


async def test_message_agent_no_agents_does_nothing(agents_app) -> None:
    """No agents in job → action_message_agent is a no-op."""
    app, job = agents_app
    job.agents.clear()

    async with app.run_test() as pilot:
        app.screen.query_one("#jobs-table").focus()
        await pilot.press("enter")
        await pilot.pause()

        screen = app.screen
        push_calls = []
        screen.app.push_screen = lambda *a, **kw: push_calls.append(True)
        job.send_message = AsyncMock(return_value=True)

        screen.action_message_agent()
        assert push_calls == []
        job.send_message.assert_not_awaited()


# ── CLI run command ───────────────────────────────────────────────────────────


def test_cli_run_success(tmp_path) -> None:
    """run command exits 0 and prints done on success."""
    import yaml
    from claude_code_sdk.types import ResultMessage
    from click.testing import CliRunner

    from claude_dispatch.cli import run

    runner = CliRunner()

    def fake_result():
        return ResultMessage(
            subtype="result",
            duration_ms=10,
            duration_api_ms=5,
            is_error=False,
            num_turns=1,
            session_id="s1",
            total_cost_usd=0.002,
        )

    call_count = 0

    async def fake_query(prompt, options):
        nonlocal call_count
        call_count += 1
        if call_count == 1 and options.cwd:
            plan_path = __import__("pathlib").Path(options.cwd) / "job-plan.yaml"
            plan_path.write_text(yaml.dump({"summary": "s", "agents": []}))
        yield fake_result()

    with patch("claude_dispatch.agent.query", fake_query):
        result = runner.invoke(run, ["fix the test"])

    assert result.exit_code == 0
    assert "done" in result.output


def test_cli_run_streams_agent_logs(tmp_path) -> None:
    """Logs emitted by agents appear in stdout."""
    import yaml
    from claude_code_sdk.types import AssistantMessage, ResultMessage, TextBlock
    from click.testing import CliRunner

    from claude_dispatch.cli import run

    runner = CliRunner()

    call_count = 0

    async def fake_query(prompt, options):
        nonlocal call_count
        call_count += 1
        if call_count == 1 and options.cwd:
            plan_path = __import__("pathlib").Path(options.cwd) / "job-plan.yaml"
            plan_path.write_text(yaml.dump({"summary": "s", "agents": []}))
        yield AssistantMessage(
            content=[TextBlock(text="I am the plan agent")], model="claude-haiku-4-5"
        )
        yield ResultMessage(
            subtype="result",
            duration_ms=10,
            duration_api_ms=5,
            is_error=False,
            num_turns=1,
            session_id="s1",
            total_cost_usd=0.001,
        )

    with patch("claude_dispatch.agent.query", fake_query):
        result = runner.invoke(run, ["do something"])

    assert "I am the plan agent" in result.output


def test_cli_run_failure_exits_nonzero() -> None:
    """run command exits 1 if job.run() raises."""
    from click.testing import CliRunner

    from claude_dispatch.cli import run

    async def fake_query(prompt, options):
        raise RuntimeError("SDK exploded")
        yield  # make it a generator

    with patch("claude_dispatch.agent.query", fake_query):
        runner = CliRunner()
        result = runner.invoke(run, ["do something"])

    assert result.exit_code == 1
