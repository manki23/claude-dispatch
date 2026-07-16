"""Tests for CostGuard and its integration into the Job lifecycle."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from claude_dispatch.agent import AgentSpec, AgentStatus, AgentType
from claude_dispatch.config import Config, CostLimits
from claude_dispatch.cost_guard import CostGuard, CostLimitExceeded
from claude_dispatch.job import Job
from claude_code_sdk.types import ResultMessage


# ── CostGuard unit tests ──────────────────────────────────────────────────────


def test_no_breach_when_under_limits() -> None:
    guard = CostGuard(max_per_agent=1.0, max_per_job=5.0)
    guard.check(agent_cost=0.5, job_total=1.0, agent_id="job1-code")  # must not raise


def test_per_agent_limit_breached() -> None:
    guard = CostGuard(max_per_agent=1.0, max_per_job=5.0)
    with pytest.raises(CostLimitExceeded, match="per-agent limit"):
        guard.check(agent_cost=1.01, job_total=1.01, agent_id="job1-code")


def test_per_job_limit_breached() -> None:
    guard = CostGuard(max_per_agent=10.0, max_per_job=5.0)
    with pytest.raises(CostLimitExceeded, match="per-job limit"):
        guard.check(agent_cost=2.0, job_total=5.01, agent_id="job1-code")


def test_agent_limit_checked_before_job_limit() -> None:
    """When both are breached, agent limit takes priority."""
    guard = CostGuard(max_per_agent=1.0, max_per_job=2.0)
    with pytest.raises(CostLimitExceeded, match="per-agent limit"):
        guard.check(agent_cost=1.5, job_total=3.0, agent_id="job1-code")


def test_per_agent_limit_disabled_when_zero() -> None:
    guard = CostGuard(max_per_agent=0, max_per_job=5.0)
    guard.check(agent_cost=999.0, job_total=1.0, agent_id="j")  # must not raise


def test_per_job_limit_disabled_when_zero() -> None:
    guard = CostGuard(max_per_agent=1.0, max_per_job=0)
    guard.check(agent_cost=0.5, job_total=999.0, agent_id="j")  # must not raise


def test_both_limits_disabled() -> None:
    guard = CostGuard(max_per_agent=0, max_per_job=0)
    guard.check(agent_cost=999.0, job_total=999.0, agent_id="j")  # must not raise


def test_exactly_at_limit_does_not_raise() -> None:
    guard = CostGuard(max_per_agent=1.0, max_per_job=5.0)
    guard.check(agent_cost=1.0, job_total=5.0, agent_id="j")  # == is OK, only > raises


def test_error_message_contains_agent_id() -> None:
    guard = CostGuard(max_per_agent=1.0, max_per_job=5.0)
    with pytest.raises(CostLimitExceeded, match="job1-code"):
        guard.check(agent_cost=1.5, job_total=1.5, agent_id="job1-code")


# ── _make_on_cost callback ────────────────────────────────────────────────────


def make_job(max_per_agent: float = 1.0, max_per_job: float = 5.0) -> Job:
    config = Config(
        limits=CostLimits(max_cost_per_agent=max_per_agent, max_cost_per_job=max_per_job),
    )
    return Job(description="test", config=config, db_enabled=False)


def test_make_on_cost_updates_job_total() -> None:
    from claude_dispatch.agent import Agent

    job = make_job()
    guard = job._make_guard()
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-code",
    )
    agent.cost_usd = 0.3
    job.agents.append(agent)

    on_cost = job._make_on_cost(agent, guard)
    on_cost(0.3)  # must not raise; job.cost_usd should be updated

    assert job.cost_usd == pytest.approx(0.3)


def test_make_on_cost_raises_on_agent_breach() -> None:
    from claude_dispatch.agent import Agent

    job = make_job(max_per_agent=0.5)
    guard = job._make_guard()
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-code",
    )
    agent.cost_usd = 0.6
    job.agents.append(agent)

    on_cost = job._make_on_cost(agent, guard)
    with pytest.raises(CostLimitExceeded, match="per-agent limit"):
        on_cost(0.6)


def test_make_on_cost_raises_on_job_breach() -> None:
    from claude_dispatch.agent import Agent

    job = make_job(max_per_agent=10.0, max_per_job=1.0)
    guard = job._make_guard()

    # Two agents, combined cost over limit
    a1 = Agent(spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"), job_id=job.job_id, agent_id="j-code")
    a2 = Agent(spec=AgentSpec(type=AgentType.TEST, cwd="/tmp"), job_id=job.job_id, agent_id="j-test")
    a1.cost_usd = 0.6
    a2.cost_usd = 0.6
    job.agents.extend([a1, a2])

    on_cost = job._make_on_cost(a2, guard)
    with pytest.raises(CostLimitExceeded, match="per-job limit"):
        on_cost(0.6)  # job total = 1.2 > 1.0


# ── integration: plan phase ───────────────────────────────────────────────────


def result_msg(session_id: str = "sess-1", cost: float = 0.005) -> ResultMessage:
    return ResultMessage(
        subtype="result",
        duration_ms=50,
        duration_api_ms=40,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=cost,
    )


@pytest.mark.asyncio
async def test_plan_phase_killed_when_agent_exceeds_limit(tmp_path: Path) -> None:
    """Plan agent cost > max_per_agent → CostLimitExceeded propagates out of run()."""
    job = make_job(max_per_agent=0.001)  # very low limit
    job._workdir = tmp_path

    async def fake_query(prompt, options):
        (tmp_path / "job-plan.yaml").write_text(
            yaml.dump({"summary": "s", "agents": []})
        )
        yield result_msg(cost=0.01)  # 0.01 > 0.001 → breaches limit

    with patch("claude_dispatch.agent.query", fake_query):
        with pytest.raises(CostLimitExceeded, match="per-agent limit"):
            await job._run_plan_phase()

    assert job.agents[0].status == AgentStatus.FAILED


@pytest.mark.asyncio
async def test_plan_phase_succeeds_under_limit(tmp_path: Path) -> None:
    job = make_job(max_per_agent=1.0)
    job._workdir = tmp_path

    async def fake_query(prompt, options):
        (tmp_path / "job-plan.yaml").write_text(
            yaml.dump({"summary": "s", "agents": []})
        )
        yield result_msg(cost=0.005)

    with patch("claude_dispatch.agent.query", fake_query):
        await job._run_plan_phase()  # must not raise

    assert job.agents[0].status == AgentStatus.DONE


# ── integration: execute phase ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_phase_kills_agent_on_cost_breach(tmp_path: Path) -> None:
    """code agent exceeds per-agent limit → marked FAILED; test agent still runs."""
    plan = {
        "summary": "s",
        "agents": [
            {"type": "code", "cwd": str(tmp_path)},
            {"type": "test", "cwd": str(tmp_path), "depends_on": ["code"]},
        ],
    }
    (tmp_path / "job-plan.yaml").write_text(yaml.dump(plan))

    job = make_job(max_per_agent=0.001)  # very low — code agent will breach
    job._workdir = tmp_path

    async def fake_query(prompt, options):
        yield result_msg(cost=0.01)  # always breaches 0.001 limit

    with patch("claude_dispatch.agent.query", fake_query):
        with pytest.raises(RuntimeError, match="agents failed"):
            await job._run_execute_phase()

    exec_agents = [a for a in job.agents if a.spec.type != AgentType.PLAN]
    code_agent = next(a for a in exec_agents if a.spec.type == AgentType.CODE)
    assert code_agent.status == AgentStatus.FAILED


@pytest.mark.asyncio
async def test_execute_phase_job_limit_stops_second_agent(tmp_path: Path) -> None:
    """Combined cost of two agents exceeds per-job limit."""
    plan = {
        "summary": "s",
        "agents": [
            {"type": "code", "cwd": str(tmp_path)},
            {"type": "jira", "cwd": str(tmp_path)},
        ],
    }
    (tmp_path / "job-plan.yaml").write_text(yaml.dump(plan))

    # Each agent costs 0.06; job limit 0.1 → first agent OK, second breaches
    job = make_job(max_per_agent=10.0, max_per_job=0.1)
    job._workdir = tmp_path

    async def fake_query(prompt, options):
        yield result_msg(cost=0.06)

    with patch("claude_dispatch.agent.query", fake_query):
        with pytest.raises(RuntimeError, match="agents failed"):
            await job._run_execute_phase()


@pytest.mark.asyncio
async def test_execute_phase_succeeds_under_limits(tmp_path: Path) -> None:
    plan = {
        "summary": "s",
        "agents": [{"type": "code", "cwd": str(tmp_path)}],
    }
    (tmp_path / "job-plan.yaml").write_text(yaml.dump(plan))

    job = make_job(max_per_agent=1.0, max_per_job=5.0)
    job._workdir = tmp_path

    async def fake_query(prompt, options):
        yield result_msg(cost=0.005)

    with patch("claude_dispatch.agent.query", fake_query):
        await job._run_execute_phase()

    exec_agents = [a for a in job.agents if a.spec.type != AgentType.PLAN]
    assert exec_agents[0].status == AgentStatus.DONE
