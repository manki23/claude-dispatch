"""Tests for ConversationThread, Turn, and ConversationScreen."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from claude_code_sdk.types import ResultMessage

from claude_dispatch.agent import Agent, AgentSpec, AgentStatus, AgentType, ConversationThread, Turn
from claude_dispatch.config import Config
from claude_dispatch.job import Job


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


# ── Turn ──────────────────────────────────────────────────────────────────────


def test_turn_user() -> None:
    t = Turn(role="user", text="hello")
    assert t.role == "user"
    assert t.text == "hello"


def test_turn_assistant() -> None:
    t = Turn(role="assistant", text="hi there")
    assert t.role == "assistant"


# ── ConversationThread ────────────────────────────────────────────────────────


def test_thread_starts_empty() -> None:
    thread = ConversationThread()
    assert thread.turns == []
    assert thread.on_reply is None


def test_thread_add_user() -> None:
    thread = ConversationThread()
    thread.add_user("what is 2+2?")
    assert len(thread.turns) == 1
    assert thread.turns[0].role == "user"
    assert thread.turns[0].text == "what is 2+2?"


def test_thread_add_assistant() -> None:
    thread = ConversationThread()
    thread.add_assistant("four")
    assert len(thread.turns) == 1
    assert thread.turns[0].role == "assistant"


def test_thread_on_reply_called() -> None:
    received: list[Turn] = []
    thread = ConversationThread(on_reply=received.append)
    thread.add_user("ping")
    assert received == []  # only assistant turns fire callback
    thread.add_assistant("pong")
    assert len(received) == 1
    assert received[0].role == "assistant"
    assert received[0].text == "pong"


def test_thread_on_reply_not_called_for_user_turn() -> None:
    received: list[Turn] = []
    thread = ConversationThread(on_reply=received.append)
    thread.add_user("hello")
    assert received == []


# ── Agent.get_or_create_conversation ─────────────────────────────────────────


def test_get_or_create_conversation_creates_on_first_call() -> None:
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id="j1",
        agent_id="j1-code",
    )
    assert agent.conversation is None
    thread = agent.get_or_create_conversation()
    assert isinstance(thread, ConversationThread)
    assert agent.conversation is thread


def test_get_or_create_conversation_returns_same_thread() -> None:
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id="j1",
        agent_id="j1-code",
    )
    t1 = agent.get_or_create_conversation()
    t2 = agent.get_or_create_conversation()
    assert t1 is t2


# ── Agent._run_turn: thread population ───────────────────────────────────────


@pytest.mark.asyncio
async def test_run_turn_populates_user_turn_when_thread_exists() -> None:
    """User prompt is recorded in thread as a 'user' turn."""
    from claude_code_sdk.types import AssistantMessage, TextBlock

    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id="j1",
        agent_id="j1-code",
    )
    agent.get_or_create_conversation()

    async def fake_query(prompt, options):
        yield AssistantMessage(content=[TextBlock(text="done")], model="claude-haiku-4-5")
        yield result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await agent.run("do the thing")

    assert agent.conversation is not None
    user_turns = [t for t in agent.conversation.turns if t.role == "user"]
    assert len(user_turns) == 1
    assert user_turns[0].text == "do the thing"


@pytest.mark.asyncio
async def test_run_turn_populates_assistant_turn() -> None:
    """TextBlock responses are recorded as 'assistant' turns."""
    from claude_code_sdk.types import AssistantMessage, TextBlock

    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id="j1",
        agent_id="j1-code",
    )
    agent.get_or_create_conversation()

    async def fake_query(prompt, options):
        yield AssistantMessage(
            content=[TextBlock(text="hello"), TextBlock(text=" world")],
            model="claude-haiku-4-5",
        )
        yield result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await agent.run("hi")

    assert agent.conversation is not None
    assistant_turns = [t for t in agent.conversation.turns if t.role == "assistant"]
    assert len(assistant_turns) == 1
    assert "hello" in assistant_turns[0].text
    assert "world" in assistant_turns[0].text


@pytest.mark.asyncio
async def test_run_turn_excludes_tool_calls_from_thread() -> None:
    """ToolUseBlock events do NOT produce assistant turns."""
    from claude_code_sdk.types import AssistantMessage, ToolUseBlock

    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id="j1",
        agent_id="j1-code",
    )
    agent.get_or_create_conversation()

    async def fake_query(prompt, options):
        yield AssistantMessage(
            content=[ToolUseBlock(id="t1", name="Bash", input={"command": "ls"})],
            model="claude-haiku-4-5",
        )
        yield result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await agent.run("list files")

    assert agent.conversation is not None
    assistant_turns = [t for t in agent.conversation.turns if t.role == "assistant"]
    assert assistant_turns == []


@pytest.mark.asyncio
async def test_run_turn_no_thread_no_error() -> None:
    """If conversation is None (not activated), _run_turn still works fine."""
    from claude_code_sdk.types import AssistantMessage, TextBlock

    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id="j1",
        agent_id="j1-code",
    )
    assert agent.conversation is None

    async def fake_query(prompt, options):
        yield AssistantMessage(content=[TextBlock(text="ok")], model="claude-haiku-4-5")
        yield result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await agent.run("do work")  # must not raise

    assert agent.conversation is None  # still None — untouched


@pytest.mark.asyncio
async def test_multi_turn_conversation_thread() -> None:
    """Inbox messages become consecutive user+assistant turns."""
    from claude_code_sdk.types import AssistantMessage, TextBlock

    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id="j1",
        agent_id="j1-code",
    )
    agent.get_or_create_conversation()

    call_count = 0

    async def fake_query(prompt, options):
        nonlocal call_count
        call_count += 1
        yield AssistantMessage(
            content=[TextBlock(text=f"reply{call_count}")], model="claude-haiku-4-5"
        )
        yield result_msg(session_id=f"s{call_count}")

    agent._inbox.put_nowait("follow-up question")

    with patch("claude_dispatch.agent.query", fake_query):
        await agent.run("first question")

    assert call_count == 2
    assert agent.conversation is not None
    roles = [t.role for t in agent.conversation.turns]
    # user → assistant → user → assistant
    assert roles == ["user", "assistant", "user", "assistant"]


# ── ConversationScreen ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_conversation_screen_renders_existing_turns() -> None:
    """Existing turns in the thread are rendered on mount."""
    from claude_dispatch.ui.screens.conversation import ConversationScreen

    job = Job(description="test job", config=Config(), db_enabled=False)
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-code",
        status=AgentStatus.RUNNING,
    )
    job.agents = [agent]

    thread = agent.get_or_create_conversation()
    thread.add_user("hello agent")
    thread.add_assistant("hello user")

    from textual.app import App, ComposeResult

    class TestApp(App):
        def compose(self) -> ComposeResult:
            return iter([])

        def on_mount(self) -> None:
            self.push_screen(ConversationScreen(job=job, agent=agent))

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        screen = app.screen
        assert isinstance(screen, ConversationScreen)
        # Both turns rendered — check thread size matches
        assert len(thread.turns) == 2


@pytest.mark.asyncio
async def test_conversation_screen_reuses_existing_thread() -> None:
    """Opening ConversationScreen twice for the same agent reuses thread."""
    from claude_dispatch.ui.screens.conversation import ConversationScreen

    job = Job(description="t", config=Config(), db_enabled=False)
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-code",
        status=AgentStatus.RUNNING,
    )
    job.agents = [agent]

    screen1 = ConversationScreen(job=job, agent=agent)
    screen2 = ConversationScreen(job=job, agent=agent)

    assert screen1._thread is screen2._thread


@pytest.mark.asyncio
async def test_conversation_screen_restores_on_reply_on_unmount() -> None:
    """on_reply callback is restored when screen is popped."""
    from claude_dispatch.ui.screens.conversation import ConversationScreen

    sentinel_called: list[Turn] = []
    original_on_reply = sentinel_called.append

    job = Job(description="t", config=Config(), db_enabled=False)
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-code",
        status=AgentStatus.RUNNING,
    )
    job.agents = [agent]

    thread = agent.get_or_create_conversation()
    thread.on_reply = original_on_reply

    from textual.app import App, ComposeResult

    class TestApp(App):
        def compose(self) -> ComposeResult:
            return iter([])

        def on_mount(self) -> None:
            self.push_screen(ConversationScreen(job=job, agent=agent))

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        await pilot.press("escape")
        await pilot.pause(0.1)

    # After unmount, original callback restored
    assert thread.on_reply is original_on_reply


@pytest.mark.asyncio
async def test_conversation_screen_esc_pops_screen() -> None:
    """Esc pops ConversationScreen, returning to previous screen."""
    from claude_dispatch.ui.screens.conversation import ConversationScreen

    job = Job(description="t", config=Config(), db_enabled=False)
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-code",
        status=AgentStatus.RUNNING,
    )
    job.agents = [agent]

    from textual.app import App, ComposeResult
    from textual.widgets import Label

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield Label("base", id="base")

        def on_mount(self) -> None:
            self.push_screen(ConversationScreen(job=job, agent=agent))

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        assert isinstance(app.screen, ConversationScreen)
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, ConversationScreen)
