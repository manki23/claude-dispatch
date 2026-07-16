"""Agent unit tests — verify SDK wiring, status transitions, callbacks."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from claude_dispatch.agent import (
    Agent,
    AgentSpec,
    AgentStatus,
    AgentType,
    AGENT_DEFAULT_MODELS,
    AGENT_DEFAULT_TOOLS,
)
from claude_code_sdk.types import (
    AssistantMessage,
    HookContext,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)


def make_agent(agent_type: AgentType = AgentType.CODE) -> Agent:
    spec = AgentSpec(type=agent_type, cwd="/tmp/test")
    return Agent(spec=spec, job_id="abc123", agent_id="abc123-code")


# ── property tests ────────────────────────────────────────────────────────────


def test_model_defaults_by_type() -> None:
    for agent_type in AgentType:
        agent = make_agent(agent_type)
        assert agent.model == AGENT_DEFAULT_MODELS[agent_type]


def test_model_spec_override() -> None:
    spec = AgentSpec(type=AgentType.CODE, model="claude-opus-4-6")
    agent = Agent(spec=spec, job_id="x", agent_id="x-code")
    assert agent.model == "claude-opus-4-6"


def test_effective_tools_defaults() -> None:
    agent = make_agent(AgentType.CODE)
    assert agent.effective_tools == AGENT_DEFAULT_TOOLS[AgentType.CODE]


def test_effective_tools_spec_override() -> None:
    spec = AgentSpec(type=AgentType.CODE, allowed_tools=["Bash"])
    agent = Agent(spec=spec, job_id="x", agent_id="x-code")
    assert agent.effective_tools == ["Bash"]


# ── callback tests ────────────────────────────────────────────────────────────


def test_set_status_fires_callback() -> None:
    received: list[AgentStatus] = []
    agent = make_agent()
    agent.on_status = received.append
    agent._set_status(AgentStatus.RUNNING)
    assert received == [AgentStatus.RUNNING]


def test_append_log_fires_callback() -> None:
    received: list[str] = []
    agent = make_agent()
    agent.on_log = received.append
    agent._append_log("hello")
    assert received == ["hello"]
    assert agent.log_lines == ["hello"]


# ── run() integration (mocked SDK) ────────────────────────────────────────────


def _make_result_message(session_id: str = "sess-1", is_error: bool = False) -> ResultMessage:
    return ResultMessage(
        subtype="result",
        duration_ms=100,
        duration_api_ms=80,
        is_error=is_error,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=0.0042,
    )


def _make_assistant_message(text: str = "done", tool_name: str | None = None) -> AssistantMessage:
    content: list[Any] = [TextBlock(text=text)]
    if tool_name:
        content.append(ToolUseBlock(id="tu-1", name=tool_name, input={}))
    return AssistantMessage(content=content, model="claude-haiku-4-5-20251001")


async def _fake_query(messages: list[Any]):
    """Returns an async generator that yields the given messages."""
    async def _gen(*args: Any, **kwargs: Any):
        for msg in messages:
            yield msg
    return _gen


@pytest.mark.asyncio
async def test_run_success() -> None:
    result_msg = _make_result_message("sess-42")
    assistant_msg = _make_assistant_message("Hello from agent")

    async def fake_query(prompt, options):
        yield assistant_msg
        yield result_msg

    with patch("claude_dispatch.agent.query", fake_query):
        agent = make_agent()
        sid = await agent.run("do something")

    assert sid == "sess-42"
    assert agent.session_id == "sess-42"
    assert agent.status == AgentStatus.DONE
    assert agent.cost_usd == pytest.approx(0.0042)
    assert "Hello from agent" in agent.log_lines


@pytest.mark.asyncio
async def test_run_error_result() -> None:
    result_msg = _make_result_message("sess-err", is_error=True)

    async def fake_query(prompt, options):
        yield result_msg

    with patch("claude_dispatch.agent.query", fake_query):
        agent = make_agent()
        await agent.run("do something")

    assert agent.status == AgentStatus.FAILED


@pytest.mark.asyncio
async def test_run_records_tool_use() -> None:
    assistant_msg = _make_assistant_message("ok", tool_name="Bash")
    result_msg = _make_result_message()

    async def fake_query(prompt, options):
        yield assistant_msg
        yield result_msg

    with patch("claude_dispatch.agent.query", fake_query):
        agent = make_agent()
        await agent.run("run tests")

    assert agent.last_action == "Bash(...)"
    assert "[tool] Bash" in agent.log_lines


@pytest.mark.asyncio
async def test_run_exception_sets_failed() -> None:
    async def fake_query(prompt, options):
        raise RuntimeError("SDK exploded")
        yield  # make it a generator

    with patch("claude_dispatch.agent.query", fake_query):
        agent = make_agent()
        with pytest.raises(RuntimeError):
            await agent.run("boom")

    assert agent.status == AgentStatus.FAILED


@pytest.mark.asyncio
async def test_run_callbacks_fired() -> None:
    statuses: list[AgentStatus] = []
    logs: list[str] = []
    costs: list[float] = []

    result_msg = _make_result_message()
    assistant_msg = _make_assistant_message("hi")

    async def fake_query(prompt, options):
        yield assistant_msg
        yield result_msg

    with patch("claude_dispatch.agent.query", fake_query):
        agent = make_agent()
        agent.on_status = statuses.append
        agent.on_log = logs.append
        agent.on_cost = costs.append
        await agent.run("go")

    assert AgentStatus.RUNNING in statuses
    assert AgentStatus.DONE in statuses
    assert "hi" in logs
    assert len(costs) > 0
