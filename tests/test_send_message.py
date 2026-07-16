"""Tests for Agent.send_message / inbox loop and Job.send_message routing."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from claude_code_sdk.types import AssistantMessage, ResultMessage, TextBlock

from claude_dispatch.agent import Agent, AgentSpec, AgentStatus, AgentType
from claude_dispatch.config import Config
from claude_dispatch.job import Job

# ── helpers ───────────────────────────────────────────────────────────────────


def result_msg(session_id: str = "sess-1", cost: float = 0.001) -> ResultMessage:
    return ResultMessage(
        subtype="result",
        duration_ms=50,
        duration_api_ms=40,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=cost,
    )


def text_msg(text: str) -> AssistantMessage:
    return AssistantMessage(content=[TextBlock(type="text", text=text)])


def make_agent(agent_type: AgentType = AgentType.CODE) -> Agent:
    return Agent(
        spec=AgentSpec(type=agent_type, cwd="/tmp"),
        job_id="job1",
        agent_id=f"job1-{agent_type.value}",
    )


def make_job() -> Job:
    return Job(description="test", config=Config(), db_enabled=False)


# ── Agent.send_message: inbox queuing ────────────────────────────────────────


def test_send_message_enqueues_text() -> None:
    agent = make_agent()
    agent.send_message("hello")
    assert agent._inbox.qsize() == 1
    assert agent._inbox.get_nowait() == "hello"


def test_send_message_appends_to_log() -> None:
    agent = make_agent()
    agent.send_message("do the thing")
    assert any("do the thing" in line for line in agent.log_lines)


def test_send_message_multiple_enqueued_in_order() -> None:
    agent = make_agent()
    agent.send_message("first")
    agent.send_message("second")
    assert agent._inbox.get_nowait() == "first"
    assert agent._inbox.get_nowait() == "second"


# ── Agent.run: turn loop drains inbox ────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_single_turn_no_inbox() -> None:
    """Single prompt, no queued messages → one SDK call."""
    agent = make_agent()
    calls: list[str] = []

    async def fake_query(prompt, options):
        calls.append(prompt)
        yield result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        session = await agent.run("do work")

    assert len(calls) == 1
    assert calls[0] == "do work"
    assert session == "sess-1"
    assert agent.status == AgentStatus.DONE


@pytest.mark.asyncio
async def test_run_drains_inbox_as_second_turn() -> None:
    """Message pre-loaded in inbox → two SDK calls."""
    agent = make_agent()
    agent.send_message("follow-up task")
    calls: list[str] = []

    async def fake_query(prompt, options):
        calls.append(prompt)
        yield result_msg(session_id=f"sess-{len(calls)}")

    with patch("claude_dispatch.agent.query", fake_query):
        await agent.run("initial prompt")

    assert len(calls) == 2
    assert calls[0] == "initial prompt"
    assert calls[1] == "follow-up task"
    assert agent.status == AgentStatus.DONE


@pytest.mark.asyncio
async def test_run_second_turn_uses_resume_session_id() -> None:
    """Second turn passes resume=session_id from the first turn."""
    agent = make_agent()
    agent.send_message("second prompt")
    resume_ids: list[str | None] = []

    async def fake_query(prompt, options):
        resume_ids.append(options.resume)
        yield result_msg(session_id="sess-A")

    with patch("claude_dispatch.agent.query", fake_query):
        await agent.run("first prompt")

    assert resume_ids[0] is None  # first turn: no resume
    assert resume_ids[1] == "sess-A"  # second turn: resume from first


@pytest.mark.asyncio
async def test_run_drains_multiple_inbox_messages() -> None:
    """Three queued messages → four SDK calls total."""
    agent = make_agent()
    for i in range(3):
        agent.send_message(f"msg-{i}")
    calls: list[str] = []

    async def fake_query(prompt, options):
        calls.append(prompt)
        yield result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await agent.run("initial")

    assert len(calls) == 4
    assert calls[0] == "initial"
    assert calls[1:] == ["msg-0", "msg-1", "msg-2"]


@pytest.mark.asyncio
async def test_run_logs_resuming_message() -> None:
    agent = make_agent()
    agent.send_message("queued")

    async def fake_query(prompt, options):
        yield result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await agent.run("start")

    assert any("[resuming with queued message]" in line for line in agent.log_lines)


# ── Job._find_message_target ──────────────────────────────────────────────────


def test_find_target_by_type() -> None:
    job = make_job()
    code_agent = make_agent(AgentType.CODE)
    test_agent = make_agent(AgentType.TEST)
    job.agents.extend([code_agent, test_agent])

    result = job._find_message_target("test")
    assert result is test_agent


def test_find_target_by_type_not_found_returns_none() -> None:
    job = make_job()
    job.agents.append(make_agent(AgentType.CODE))
    assert job._find_message_target("jira") is None


def test_find_target_prefers_running_agent() -> None:
    job = make_job()
    done_agent = make_agent(AgentType.CODE)
    done_agent.status = AgentStatus.DONE
    done_agent.session_id = "sess-done"
    running_agent = make_agent(AgentType.TEST)
    running_agent.status = AgentStatus.RUNNING
    job.agents.extend([done_agent, running_agent])

    assert job._find_message_target() is running_agent


def test_find_target_falls_back_to_last_done_with_session() -> None:
    job = make_job()
    done1 = make_agent(AgentType.CODE)
    done1.status = AgentStatus.DONE
    done1.session_id = "sess-1"
    done2 = make_agent(AgentType.TEST)
    done2.status = AgentStatus.DONE
    done2.session_id = "sess-2"
    job.agents.extend([done1, done2])

    assert job._find_message_target() is done2  # last one


def test_find_target_done_without_session_id_skipped() -> None:
    job = make_job()
    done_no_sess = make_agent(AgentType.CODE)
    done_no_sess.status = AgentStatus.DONE
    done_no_sess.session_id = None
    job.agents.append(done_no_sess)

    assert job._find_message_target() is None


def test_find_target_empty_job_returns_none() -> None:
    job = make_job()
    assert job._find_message_target() is None


# ── Job.send_message: routing ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_send_message_to_running_agent_enqueues() -> None:
    job = make_job()
    agent = make_agent(AgentType.CODE)
    agent.status = AgentStatus.RUNNING
    job.agents.append(agent)

    result = await job.send_message("please stop")
    assert result is True
    assert agent._inbox.qsize() == 1
    assert agent._inbox.get_nowait() == "please stop"


@pytest.mark.asyncio
async def test_job_send_message_no_target_returns_false() -> None:
    job = make_job()
    result = await job.send_message("hello")
    assert result is False


@pytest.mark.asyncio
async def test_job_send_message_to_done_agent_creates_task() -> None:
    """DONE agent with session_id → new SDK turn spawned as background task."""
    job = make_job()
    agent = make_agent(AgentType.CODE)
    agent.status = AgentStatus.DONE
    agent.session_id = "sess-xyz"
    job.agents.append(agent)

    spawned_prompts: list[str] = []

    async def fake_query(prompt, options):
        spawned_prompts.append(prompt)
        yield result_msg(session_id="sess-xyz-2")

    with patch("claude_dispatch.agent.query", fake_query):
        result = await job.send_message("resume work")
        # Let the background task run
        await asyncio.sleep(0)
        # Give the task a chance to complete
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        await asyncio.gather(*pending, return_exceptions=True)

    assert result is True
    assert spawned_prompts == ["resume work"]


@pytest.mark.asyncio
async def test_job_send_message_routes_by_agent_type() -> None:
    job = make_job()
    code_agent = make_agent(AgentType.CODE)
    code_agent.status = AgentStatus.RUNNING
    test_agent = make_agent(AgentType.TEST)
    test_agent.status = AgentStatus.RUNNING
    job.agents.extend([code_agent, test_agent])

    await job.send_message("only for test", agent_type="test")
    assert test_agent._inbox.qsize() == 1
    assert code_agent._inbox.qsize() == 0


@pytest.mark.asyncio
async def test_job_send_message_preserves_resume_session_id() -> None:
    """Done agent's run() is called with its existing session_id for context continuity."""
    job = make_job()
    agent = make_agent(AgentType.CODE)
    agent.status = AgentStatus.DONE
    agent.session_id = "my-session"
    job.agents.append(agent)

    captured_resume: list[str | None] = []

    async def fake_query(prompt, options):
        captured_resume.append(options.resume)
        yield result_msg(session_id="my-session-2")

    with patch("claude_dispatch.agent.query", fake_query):
        await job.send_message("continue")
        await asyncio.gather(
            *[t for t in asyncio.all_tasks() if t is not asyncio.current_task()],
            return_exceptions=True,
        )

    assert captured_resume == ["my-session"]
