"""Tests for the dependency-aware agent scheduler (_schedule_agents)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from claude_dispatch.agent import Agent, AgentSpec, AgentStatus, AgentType
from claude_dispatch.config import Config, Defaults
from claude_dispatch.job import Job
from claude_code_sdk.types import ResultMessage


# ── helpers ───────────────────────────────────────────────────────────────────


def make_job(max_parallel: int = 5) -> Job:
    config = Config(defaults=Defaults(max_parallel_agents=max_parallel))
    return Job(description="Test job", config=config)


def make_agent(agent_type: AgentType, depends_on: list[str] | None = None) -> Agent:
    spec = AgentSpec(type=agent_type, cwd="/tmp/test", depends_on=depends_on or [])
    return Agent(spec=spec, job_id="job1", agent_id=f"job1-{agent_type.value}")


def result_msg(is_error: bool = False) -> ResultMessage:
    return ResultMessage(
        subtype="result",
        duration_ms=50,
        duration_api_ms=40,
        is_error=is_error,
        num_turns=1,
        session_id="sess-x",
        total_cost_usd=0.001,
    )


def fake_query_ok():
    async def _q(prompt, options):
        yield result_msg()

    return _q


def fake_query_error():
    async def _q(prompt, options):
        yield result_msg(is_error=True)

    return _q


def fake_query_raises():
    async def _q(prompt, options):
        raise RuntimeError("agent exploded")
        yield  # make it a generator

    return _q


# ── parallel execution (no deps) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_independent_agents_run_in_parallel() -> None:
    """code + jira have no deps → both should be RUNNING simultaneously."""
    job = make_job()
    code = make_agent(AgentType.CODE)
    jira = make_agent(AgentType.JIRA)

    started: list[str] = []
    barrier = asyncio.Event()

    async def fake_query(prompt, options):
        started.append(options.cwd or "?")
        await barrier.wait()
        yield result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        task = asyncio.create_task(job._schedule_agents([code, jira]))
        # Give both agents time to start
        await asyncio.sleep(0.05)
        assert len(started) == 2, "Both agents should have started before barrier"
        barrier.set()
        await task

    assert code.status == AgentStatus.DONE
    assert jira.status == AgentStatus.DONE


# ── ordering (with deps) ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dependent_agent_waits_for_prerequisite() -> None:
    """test depends_on code → test must not start before code finishes."""
    job = make_job()
    code = make_agent(AgentType.CODE)
    test = make_agent(AgentType.TEST, depends_on=["code"])

    finish_order: list[str] = []

    async def fake_query(prompt, options):
        yield result_msg()
        # Record which agent_type finished (read from prompt)
        if "code" in prompt:
            finish_order.append("code")
        elif "test" in prompt:
            finish_order.append("test")

    with patch("claude_dispatch.agent.query", fake_query):
        await job._schedule_agents([code, test])

    assert finish_order == ["code", "test"], "code must finish before test starts"
    assert code.status == AgentStatus.DONE
    assert test.status == AgentStatus.DONE


@pytest.mark.asyncio
async def test_chain_ordering() -> None:
    """code → test → review: must run in strict sequence."""
    job = make_job()
    code = make_agent(AgentType.CODE)
    test = make_agent(AgentType.TEST, depends_on=["code"])
    review = make_agent(AgentType.REVIEW, depends_on=["test"])

    finish_order: list[str] = []

    async def fake_query(prompt, options):
        yield result_msg()
        for t in ("code", "test", "review"):
            if t in prompt:
                finish_order.append(t)
                break

    with patch("claude_dispatch.agent.query", fake_query):
        await job._schedule_agents([code, test, review])

    assert finish_order == ["code", "test", "review"]


# ── semaphore / parallelism cap ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency() -> None:
    """With max_parallel=1, only one agent runs at a time even with no deps."""
    job = make_job(max_parallel=1)
    code = make_agent(AgentType.CODE)
    jira = make_agent(AgentType.JIRA)

    concurrent_peak = 0
    active = 0

    async def fake_query(prompt, options):
        nonlocal concurrent_peak, active
        active += 1
        concurrent_peak = max(concurrent_peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        yield result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await job._schedule_agents([code, jira])

    assert concurrent_peak == 1, "Should never exceed 1 concurrent agent"


# ── failure handling ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_failed_agent_unblocks_dependants() -> None:
    """code fails → test still gets to run (event is set regardless)."""
    job = make_job()
    code = make_agent(AgentType.CODE)
    test = make_agent(AgentType.TEST, depends_on=["code"])

    async def fake_query(prompt, options):
        if "code" in prompt:
            raise RuntimeError("code agent crashed")
        yield result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        with pytest.raises(RuntimeError, match="agents failed"):
            await job._schedule_agents([code, test])

    # code is FAILED; test ran anyway (event was set in finally)
    assert code.status == AgentStatus.FAILED
    assert test.status == AgentStatus.DONE


@pytest.mark.asyncio
async def test_all_failed_raises_runtime_error() -> None:
    job = make_job()
    code = make_agent(AgentType.CODE)
    jira = make_agent(AgentType.JIRA)

    with patch("claude_dispatch.agent.query", fake_query_raises()):
        with pytest.raises(RuntimeError, match="agents failed"):
            await job._schedule_agents([code, jira])

    assert code.status == AgentStatus.FAILED
    assert jira.status == AgentStatus.FAILED


# ── validation ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_dep_raises_value_error() -> None:
    job = make_job()
    test = make_agent(AgentType.TEST, depends_on=["code"])  # code not in plan

    with pytest.raises(ValueError, match="unknown type 'code'"):
        await job._schedule_agents([test])


@pytest.mark.asyncio
async def test_cycle_raises_value_error() -> None:
    job = make_job()
    code = make_agent(AgentType.CODE, depends_on=["test"])
    test = make_agent(AgentType.TEST, depends_on=["code"])

    with pytest.raises(ValueError, match="Cycle"):
        await job._schedule_agents([code, test])


# ── execute phase integration ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_phase_runs_agents_from_plan(tmp_path: Path) -> None:
    """_run_execute_phase() reads job-plan.yaml and schedules agents."""
    plan = {
        "summary": "test job",
        "agents": [
            {"type": "code", "cwd": str(tmp_path)},
            {"type": "test", "cwd": str(tmp_path), "depends_on": ["code"]},
        ],
    }
    (tmp_path / "job-plan.yaml").write_text(yaml.dump(plan))

    job = make_job()
    job._workdir = tmp_path

    finish_order: list[str] = []

    async def fake_query(prompt, options):
        yield result_msg()
        for t in ("code", "test"):
            if t in prompt:
                finish_order.append(t)
                break

    with patch("claude_dispatch.agent.query", fake_query):
        await job._run_execute_phase()

    # plan agent (from plan phase) not here; only execute-phase agents
    exec_agents = [a for a in job.agents if a.spec.type != AgentType.PLAN]
    assert len(exec_agents) == 2
    assert all(a.status == AgentStatus.DONE for a in exec_agents)
    assert finish_order == ["code", "test"]
