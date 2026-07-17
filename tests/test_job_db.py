"""Tests for Job ↔ DB wiring — upsert after run, resume_id lookup before run."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from claude_code_sdk.types import ResultMessage

from claude_dispatch.agent import AgentSpec, AgentStatus, AgentType
from claude_dispatch.config import Config
from claude_dispatch.db import init_db
from claude_dispatch.job import Job


def result_msg(session_id: str = "sess-1", is_error: bool = False) -> ResultMessage:
    return ResultMessage(
        subtype="result",
        duration_ms=50,
        duration_api_ms=40,
        is_error=is_error,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=0.005,
    )


@pytest.fixture
async def db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    return db_path


def make_job(db_path: Path | None = None) -> Job:
    config = Config()
    job = Job(description="test task", config=config)
    if db_path is None:
        job.db_enabled = False
    return job


# ── _db_upsert ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_db_upsert_persists_session(tmp_path: Path, db: Path) -> None:
    """After agent.run() completes, session_id is persisted in DB."""
    from claude_dispatch.agent import Agent

    job = make_job()
    job.db_enabled = True
    job._use_workers = False

    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-code",
    )
    agent.session_id = "sess-persisted"
    agent.status = AgentStatus.DONE
    agent.cost_usd = 0.007

    with patch("claude_dispatch.job.upsert_session", new_callable=AsyncMock) as mock_upsert:
        await job._db_upsert(agent)

    mock_upsert.assert_awaited_once_with(
        job_id=job.job_id,
        agent_type="code",
        session_id="sess-persisted",
        description="test task",
        instructions="",
        status="done",
        cost_usd=0.007,
    )


@pytest.mark.asyncio
async def test_db_upsert_skips_if_no_session_id() -> None:
    from claude_dispatch.agent import Agent

    job = make_job()
    job.db_enabled = True
    job._use_workers = False
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-code",
    )
    # session_id is None → nothing to persist

    with patch("claude_dispatch.job.upsert_session", new_callable=AsyncMock) as mock_upsert:
        await job._db_upsert(agent)

    mock_upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_db_upsert_swallows_exceptions() -> None:
    from claude_dispatch.agent import Agent

    job = make_job()
    job.db_enabled = True
    job._use_workers = False
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-code",
    )
    agent.session_id = "sess-x"

    with patch("claude_dispatch.job.upsert_session", side_effect=OSError("disk full")):
        await job._db_upsert(agent)  # must not raise


# ── _db_resume_id ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_db_resume_id_returns_existing_session() -> None:
    from claude_dispatch.agent import Agent

    job = make_job()
    job.db_enabled = True
    job._use_workers = False
    agent = Agent(
        spec=AgentSpec(type=AgentType.PLAN, cwd="/tmp"),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-plan",
    )

    with patch("claude_dispatch.job.get_session", new_callable=AsyncMock, return_value="old-sess"):
        resume_id = await job._db_resume_id(agent)

    assert resume_id == "old-sess"


@pytest.mark.asyncio
async def test_db_resume_id_returns_none_if_not_found() -> None:
    from claude_dispatch.agent import Agent

    job = make_job()
    job.db_enabled = True
    job._use_workers = False
    agent = Agent(
        spec=AgentSpec(type=AgentType.PLAN, cwd="/tmp"),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-plan",
    )

    with patch("claude_dispatch.job.get_session", new_callable=AsyncMock, return_value=None):
        resume_id = await job._db_resume_id(agent)

    assert resume_id is None


@pytest.mark.asyncio
async def test_db_resume_id_swallows_exceptions() -> None:
    from claude_dispatch.agent import Agent

    job = make_job()
    job.db_enabled = True
    job._use_workers = False
    agent = Agent(
        spec=AgentSpec(type=AgentType.PLAN, cwd="/tmp"),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-plan",
    )

    with patch("claude_dispatch.job.get_session", side_effect=OSError("db gone")):
        resume_id = await job._db_resume_id(agent)  # must not raise

    assert resume_id is None


# ── end-to-end: plan phase persists session ───────────────────────────────────


@pytest.mark.asyncio
async def test_plan_phase_calls_upsert_on_success(tmp_path: Path) -> None:
    job = make_job()
    job.db_enabled = True
    job._use_workers = False
    job._workdir = tmp_path

    plan_content = yaml.dump({"summary": "s", "agents": [{"type": "test", "cwd": str(tmp_path)}]})

    async def fake_query(prompt, options):
        (tmp_path / "job-plan.yaml").write_text(plan_content)
        yield result_msg("sess-plan-1")

    with (
        patch("claude_dispatch.agent.query", fake_query),
        patch("claude_dispatch.job.upsert_session", new_callable=AsyncMock) as mock_upsert,
        patch("claude_dispatch.job.get_session", new_callable=AsyncMock, return_value=None),
    ):
        await job._run_plan_phase()

    mock_upsert.assert_awaited_once()
    call_kwargs = mock_upsert.call_args.kwargs
    assert call_kwargs["session_id"] == "sess-plan-1"
    assert call_kwargs["agent_type"] == "plan"
    assert call_kwargs["job_id"] == job.job_id


@pytest.mark.asyncio
async def test_plan_phase_passes_resume_id_from_db(tmp_path: Path) -> None:
    """If DB has a prior session for plan, it must be passed as resume_session_id."""
    job = make_job()
    job.db_enabled = True
    job._use_workers = False
    job._workdir = tmp_path

    plan_content = yaml.dump({"summary": "s", "agents": [{"type": "test", "cwd": str(tmp_path)}]})
    captured_resume_ids: list[str | None] = []

    async def fake_query(prompt, options):
        captured_resume_ids.append(options.resume)
        (tmp_path / "job-plan.yaml").write_text(plan_content)
        yield result_msg("sess-plan-2")

    with (
        patch("claude_dispatch.agent.query", fake_query),
        patch("claude_dispatch.job.upsert_session", new_callable=AsyncMock),
        patch(
            "claude_dispatch.job.get_session",
            new_callable=AsyncMock,
            return_value="old-plan-sess",
        ),
    ):
        await job._run_plan_phase()

    assert captured_resume_ids == ["old-plan-sess"]


# ── end-to-end: execute phase persists sessions ───────────────────────────────


@pytest.mark.asyncio
async def test_execute_phase_upserts_all_agents(tmp_path: Path) -> None:
    plan = {"summary": "s", "agents": [
        {"type": "code", "cwd": str(tmp_path)},
        {"type": "test", "cwd": str(tmp_path), "depends_on": ["code"]},
    ]}
    (tmp_path / "job-plan.yaml").write_text(yaml.dump(plan))

    job = make_job()
    job.db_enabled = True
    job._use_workers = False
    job._workdir = tmp_path

    upserted: list[dict] = []

    async def fake_upsert(**kwargs):
        upserted.append(kwargs)

    async def fake_query(prompt, options):
        yield result_msg("sess-exec")

    with (
        patch("claude_dispatch.agent.query", fake_query),
        patch("claude_dispatch.job.upsert_session", side_effect=fake_upsert),
        patch("claude_dispatch.job.get_session", new_callable=AsyncMock, return_value=None),
    ):
        await job._run_execute_phase()

    assert len(upserted) == 2
    agent_types = {u["agent_type"] for u in upserted}
    assert agent_types == {"code", "test"}
