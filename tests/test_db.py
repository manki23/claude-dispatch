"""Tests for the SQLite session store (db.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_dispatch.db import (
    delete_job,
    get_session,
    init_db,
    list_agents,
    list_jobs,
    upsert_session,
)


@pytest.fixture
async def db(tmp_path: Path) -> Path:
    """Initialised temp DB path."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    return db_path


# ── init ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_db_creates_table(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    assert not db_path.exists()
    await init_db(db_path)
    assert db_path.exists()


@pytest.mark.asyncio
async def test_init_db_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    await init_db(db_path)  # second call must not raise


# ── upsert / get ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_and_get_session(db: Path) -> None:
    await upsert_session("job1", "code", "sess-abc", db_path=db)
    result = await get_session("job1", "code", db_path=db)
    assert result == "sess-abc"


@pytest.mark.asyncio
async def test_get_session_returns_none_if_missing(db: Path) -> None:
    result = await get_session("no-such-job", "code", db_path=db)
    assert result is None


@pytest.mark.asyncio
async def test_upsert_updates_existing_row(db: Path) -> None:
    await upsert_session("job1", "code", "sess-v1", status="running", cost_usd=0.01, db_path=db)
    await upsert_session("job1", "code", "sess-v2", status="done", cost_usd=0.05, db_path=db)

    result = await get_session("job1", "code", db_path=db)
    assert result == "sess-v2"

    agents = await list_agents("job1", db_path=db)
    assert len(agents) == 1
    assert agents[0]["status"] == "done"
    assert agents[0]["cost_usd"] == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_upsert_multiple_agents_same_job(db: Path) -> None:
    await upsert_session("job1", "code", "sess-code", db_path=db)
    await upsert_session("job1", "test", "sess-test", db_path=db)

    assert await get_session("job1", "code", db_path=db) == "sess-code"
    assert await get_session("job1", "test", db_path=db) == "sess-test"


# ── list_agents ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_agents_returns_all_for_job(db: Path) -> None:
    await upsert_session("job1", "code", "s1", cost_usd=0.01, db_path=db)
    await upsert_session("job1", "test", "s2", cost_usd=0.02, db_path=db)
    await upsert_session("job2", "code", "s3", db_path=db)  # different job

    agents = await list_agents("job1", db_path=db)
    assert len(agents) == 2
    types = {a["agent_type"] for a in agents}
    assert types == {"code", "test"}


@pytest.mark.asyncio
async def test_list_agents_empty_for_unknown_job(db: Path) -> None:
    result = await list_agents("no-such-job", db_path=db)
    assert result == []


@pytest.mark.asyncio
async def test_list_agents_row_shape(db: Path) -> None:
    await upsert_session("job1", "plan", "sess-plan", status="done", cost_usd=0.003, db_path=db)
    agents = await list_agents("job1", db_path=db)
    row = agents[0]
    assert set(row.keys()) == {"agent_type", "session_id", "status", "cost_usd", "created_at", "updated_at"}
    assert row["agent_type"] == "plan"
    assert row["session_id"] == "sess-plan"
    assert row["status"] == "done"
    assert row["cost_usd"] == pytest.approx(0.003)


# ── list_jobs ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_jobs_aggregates_cost(db: Path) -> None:
    await upsert_session("job1", "code", "s1", description="Fix bug", cost_usd=0.01, db_path=db)
    await upsert_session("job1", "test", "s2", description="Fix bug", cost_usd=0.02, db_path=db)

    jobs = await list_jobs(db_path=db)
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == "job1"
    assert jobs[0]["cost_usd"] == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_list_jobs_multiple_jobs(db: Path) -> None:
    await upsert_session("job1", "code", "s1", db_path=db)
    await upsert_session("job2", "code", "s2", db_path=db)

    jobs = await list_jobs(db_path=db)
    assert len(jobs) == 2
    job_ids = {j["job_id"] for j in jobs}
    assert job_ids == {"job1", "job2"}


@pytest.mark.asyncio
async def test_list_jobs_empty(db: Path) -> None:
    assert await list_jobs(db_path=db) == []


# ── delete_job ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_job_removes_all_agents(db: Path) -> None:
    await upsert_session("job1", "code", "s1", db_path=db)
    await upsert_session("job1", "test", "s2", db_path=db)
    await upsert_session("job2", "code", "s3", db_path=db)

    await delete_job("job1", db_path=db)

    assert await list_agents("job1", db_path=db) == []
    assert len(await list_agents("job2", db_path=db)) == 1  # job2 untouched


@pytest.mark.asyncio
async def test_delete_job_nonexistent_is_noop(db: Path) -> None:
    await delete_job("no-such-job", db_path=db)  # must not raise
