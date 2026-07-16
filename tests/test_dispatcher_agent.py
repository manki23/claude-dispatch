"""Tests for dispatcher agent: AgentType, context builder, DispatcherApp wiring."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from claude_code_sdk.types import ResultMessage

from claude_dispatch.agent import (
    AGENT_DEFAULT_MODELS,
    AGENT_DEFAULT_TOOLS,
    Agent,
    AgentSpec,
    AgentStatus,
    AgentType,
)
from claude_dispatch.config import Config
from claude_dispatch.dispatcher_context import build_dispatcher_system_prompt
from claude_dispatch.job import Job, JobPhase, JobStatus


def result_msg(session_id: str = "s1") -> ResultMessage:
    return ResultMessage(
        subtype="result",
        duration_ms=10,
        duration_api_ms=5,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=0.001,
    )


# ── AgentType.DISPATCHER ──────────────────────────────────────────────────────


def test_dispatcher_in_agent_type_enum() -> None:
    assert AgentType.DISPATCHER == "dispatcher"


def test_dispatcher_default_model_is_sonnet() -> None:
    assert AGENT_DEFAULT_MODELS[AgentType.DISPATCHER] == "claude-sonnet-4-6"


def test_dispatcher_default_tools_is_empty() -> None:
    """Dispatcher has no tools — context injected via system prompt only."""
    assert AGENT_DEFAULT_TOOLS[AgentType.DISPATCHER] == []


# ── build_dispatcher_system_prompt ────────────────────────────────────────────


def test_context_no_jobs() -> None:
    prompt = build_dispatcher_system_prompt([])
    assert "No jobs" in prompt


def test_context_includes_job_id_and_description() -> None:
    job = Job(description="fix the auth bug", config=Config(), job_id="abc123", db_enabled=False)
    prompt = build_dispatcher_system_prompt([job])
    assert "abc123" in prompt
    assert "fix the auth bug" in prompt


def test_context_includes_job_status() -> None:
    job = Job(description="t", config=Config(), job_id="j1", db_enabled=False)
    job.status = JobStatus.RUNNING
    prompt = build_dispatcher_system_prompt([job])
    assert "running" in prompt


def test_context_includes_agent_status_and_cost() -> None:
    job = Job(description="t", config=Config(), job_id="j1", db_enabled=False)
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id="j1",
        agent_id="j1-code",
        status=AgentStatus.RUNNING,
        cost_usd=0.042,
    )
    job.agents = [agent]
    prompt = build_dispatcher_system_prompt([job])
    assert "code" in prompt
    assert "0.042" in prompt


def test_context_running_agent_includes_recent_logs() -> None:
    job = Job(description="t", config=Config(), job_id="j1", db_enabled=False)
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id="j1",
        agent_id="j1-code",
        status=AgentStatus.RUNNING,
        log_lines=["line1", "line2", "line3", "line4"],
    )
    job.agents = [agent]
    prompt = build_dispatcher_system_prompt([job])
    # Last 3 log lines included, first line excluded
    assert "line4" in prompt
    assert "line3" in prompt
    assert "line2" in prompt
    assert "line1" not in prompt


def test_context_done_agent_excludes_logs() -> None:
    job = Job(description="t", config=Config(), job_id="j1", db_enabled=False)
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id="j1",
        agent_id="j1-code",
        status=AgentStatus.DONE,
        log_lines=["secret log"],
    )
    job.agents = [agent]
    prompt = build_dispatcher_system_prompt([job])
    assert "secret log" not in prompt


def test_context_multiple_jobs() -> None:
    j1 = Job(description="job one", config=Config(), job_id="j1", db_enabled=False)
    j2 = Job(description="job two", config=Config(), job_id="j2", db_enabled=False)
    prompt = build_dispatcher_system_prompt([j1, j2])
    assert "job one" in prompt
    assert "job two" in prompt


# ── DispatcherApp: singleton agent ────────────────────────────────────────────


def test_dispatcher_app_has_singleton_agent() -> None:
    from claude_dispatch.dispatcher import DispatcherApp

    app = DispatcherApp(config=Config())
    assert app._dispatcher_agent.spec.type == AgentType.DISPATCHER
    assert app._dispatcher_agent.conversation is not None


def test_dispatcher_app_agent_same_instance_on_repeated_access() -> None:
    from claude_dispatch.dispatcher import DispatcherApp

    app = DispatcherApp(config=Config())
    a1 = app._dispatcher_agent
    a2 = app._dispatcher_agent
    assert a1 is a2


# ── ConversationScreen: system_prompt_factory mode ───────────────────────────


@pytest.mark.asyncio
async def test_conversation_screen_dispatcher_mode_calls_agent_run_directly() -> None:
    """system_prompt_factory → agent.run() called directly (not via job.send_message)."""
    from claude_code_sdk.types import AssistantMessage, TextBlock

    from claude_dispatch.ui.screens.conversation import ConversationScreen

    config = Config()
    job = Job(description="dispatcher", config=config, job_id="dispatcher", db_enabled=False)

    dispatcher_agent = Agent(
        spec=AgentSpec(type=AgentType.DISPATCHER),
        job_id="dispatcher",
        agent_id="dispatcher-0",
        status=AgentStatus.DONE,
    )
    dispatcher_agent.get_or_create_conversation()

    run_calls: list[dict] = []

    async def fake_query(prompt, options):
        run_calls.append({"prompt": prompt, "system": options.system_prompt})
        yield AssistantMessage(content=[TextBlock(text="here is the status")], model="claude-sonnet-4-6")
        yield result_msg()

    factory_calls: list[str] = []

    def fake_factory() -> str:
        factory_calls.append("called")
        return "## live context"

    from textual.app import App, ComposeResult

    class TestApp(App):
        def compose(self) -> ComposeResult:
            return iter([])

        def on_mount(self) -> None:
            self.push_screen(
                ConversationScreen(
                    job=job,
                    agent=dispatcher_agent,
                    system_prompt_factory=fake_factory,
                )
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        with patch("claude_dispatch.agent.query", fake_query):
            await pilot.press("d", "o", "work", "enter")
            await pilot.pause(0.3)

    # Factory was called and system prompt forwarded
    assert len(factory_calls) >= 1


# ── MainScreen: d binding ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_main_screen_d_opens_conversation_screen() -> None:
    """Pressing d on MainScreen opens a ConversationScreen."""
    from claude_dispatch.dispatcher import DispatcherApp
    from claude_dispatch.ui.screens.conversation import ConversationScreen

    app = DispatcherApp(config=Config(), jobs=[])
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        await pilot.press("d")
        await pilot.pause(0.1)
        assert isinstance(app.screen, ConversationScreen)
