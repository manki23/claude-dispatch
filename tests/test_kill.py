"""Tests for Agent.cancel() and Job.kill() asyncio task cancellation."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from claude_code_sdk.types import ResultMessage

from claude_dispatch.agent import Agent, AgentSpec, AgentStatus, AgentType
from claude_dispatch.config import Config
from claude_dispatch.job import Job, JobStatus


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


# ── Agent.cancel() ────────────────────────────────────────────────────────────


def test_cancel_noop_when_not_running() -> None:
    """cancel() on a WAITING agent is a safe no-op."""
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id="j1",
        agent_id="j1-code",
    )
    assert agent.status == AgentStatus.WAITING
    agent.cancel()  # must not raise
    assert agent.status == AgentStatus.KILLED


def test_cancel_noop_when_done() -> None:
    """cancel() on a DONE agent sets status to KILLED (no task to cancel)."""
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id="j1",
        agent_id="j1-code",
        status=AgentStatus.DONE,
    )
    agent.cancel()
    assert agent.status == AgentStatus.KILLED


@pytest.mark.asyncio
async def test_cancel_while_running_sets_killed_status() -> None:
    """cancel() during agent.run() cancels the task and sets status to KILLED."""
    gate = asyncio.Event()

    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id="j1",
        agent_id="j1-code",
    )

    async def fake_query(prompt, options):
        gate.set()  # signal that the query has started
        await asyncio.sleep(10)  # block until cancelled
        yield result_msg()  # never reached

    async def run_and_cancel():
        task = asyncio.create_task(agent.run("do work"))
        await gate.wait()  # wait for query to start
        agent.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    with patch("claude_dispatch.agent.query", fake_query):
        await run_and_cancel()

    assert agent.status == AgentStatus.KILLED


@pytest.mark.asyncio
async def test_cancel_appends_killed_log_line() -> None:
    """cancel() during run appends '[killed]' to log_lines."""
    gate = asyncio.Event()

    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id="j1",
        agent_id="j1-code",
    )

    async def fake_query(prompt, options):
        gate.set()
        await asyncio.sleep(10)
        yield result_msg()

    async def run_and_cancel():
        task = asyncio.create_task(agent.run("do work"))
        await gate.wait()
        agent.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    with patch("claude_dispatch.agent.query", fake_query):
        await run_and_cancel()

    assert "[killed]" in agent.log_lines


@pytest.mark.asyncio
async def test_task_cleared_after_run_completes() -> None:
    """_task is None after a normal (non-cancelled) run completes."""
    from claude_code_sdk.types import AssistantMessage, TextBlock

    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id="j1",
        agent_id="j1-code",
    )

    async def fake_query(prompt, options):
        yield AssistantMessage(content=[TextBlock(text="done")], model="claude-haiku-4-5")
        yield result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await agent.run("do work")

    assert agent._task is None


# ── Job.kill() ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_kill_cancels_running_agents() -> None:
    """Job.kill() cancels all RUNNING agents via agent.cancel()."""
    gate = asyncio.Event()

    job = Job(description="t", config=Config(), db_enabled=False)

    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-code",
    )
    job.agents = [agent]

    async def fake_query(prompt, options):
        gate.set()
        await asyncio.sleep(10)
        yield result_msg()

    async def run_and_kill():
        task = asyncio.create_task(agent.run("do work"))
        await gate.wait()
        job.kill()
        try:
            await task
        except asyncio.CancelledError:
            pass

    with patch("claude_dispatch.agent.query", fake_query):
        await run_and_kill()

    assert agent.status == AgentStatus.KILLED
    assert job.status == JobStatus.KILLED


def test_job_kill_skips_non_running_agents() -> None:
    """Job.kill() only cancels RUNNING agents; others get KILLED status via cancel()."""
    job = Job(description="t", config=Config(), db_enabled=False)

    waiting = Agent(
        spec=AgentSpec(type=AgentType.TEST, cwd="/tmp"),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-test",
        status=AgentStatus.WAITING,
    )
    done = Agent(
        spec=AgentSpec(type=AgentType.PLAN),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-plan",
        status=AgentStatus.DONE,
    )
    job.agents = [waiting, done]

    job.kill()

    # Only RUNNING agents get cancel(); WAITING/DONE are left alone
    assert waiting.status == AgentStatus.WAITING
    assert done.status == AgentStatus.DONE
    assert job.status == JobStatus.KILLED


@pytest.mark.asyncio
async def test_job_kill_sets_job_status_killed() -> None:
    """Job.kill() always sets job.status = KILLED."""
    job = Job(description="t", config=Config(), db_enabled=False)
    job.kill()
    assert job.status == JobStatus.KILLED
