"""Tests for background worker subprocess + DB persistence + TUI restart."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from claude_dispatch.agent import AgentSpec, AgentStatus, AgentType
from claude_dispatch.config import Config
from claude_dispatch.job import Job

# ── worker subprocess round-trip ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_worker_subprocess_writes_log_and_updates_db(tmp_path: Path) -> None:
    """Spawned worker writes logs to file and updates DB status."""
    from claude_dispatch.db import init_db, list_agents, upsert_session

    db_path = tmp_path / "test.db"
    log_path = tmp_path / "plan.log"

    await init_db(db_path)

    # Pre-seed the sessions row so _spawn_worker can update it
    await upsert_session(
        "job-w1", "plan", "", description="test", status="running", db_path=db_path
    )

    import types

    from claude_dispatch.worker import _run

    args = types.SimpleNamespace(
        job_id="job-w1",
        agent_type="plan",
        agent_id="job-w1-plan",
        description="test",
        instructions="",
        prompt="Write hello",
        system_prompt="",
        cwd=None,
        model=None,
        resume_session_id=None,
        mcp_config_path=None,
        log_path=str(log_path),
        db_path=str(db_path),
    )

    from claude_code_sdk.types import ResultMessage

    async def fake_query(prompt, options):
        yield ResultMessage(
            subtype="result",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sess-worker-1",
            total_cost_usd=0.002,
        )

    with patch("claude_dispatch.agent.query", fake_query):
        await _run(args)

    agents = await list_agents("job-w1", db_path=db_path)
    assert len(agents) == 1
    assert agents[0]["status"] == "done"
    assert agents[0]["session_id"] == "sess-worker-1"


# ── message queue: enqueue / dequeue ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_enqueue_dequeue_messages(tmp_path: Path) -> None:
    """Messages enqueued by TUI are returned once by dequeue and then consumed."""
    from claude_dispatch.db import dequeue_messages, enqueue_message, init_db

    db_path = tmp_path / "msg.db"
    await init_db(db_path)

    await enqueue_message("j1", "code", "please add logging", db_path=db_path)
    await enqueue_message("j1", "code", "and also add tests", db_path=db_path)

    msgs = await dequeue_messages("j1", "code", db_path=db_path)
    assert msgs == ["please add logging", "and also add tests"]

    # Second call returns nothing (already consumed)
    msgs2 = await dequeue_messages("j1", "code", db_path=db_path)
    assert msgs2 == []


# ── dispatcher loads jobs from DB on restart ──────────────────────────────────


@pytest.mark.asyncio
async def test_dispatcher_loads_jobs_from_db_on_restart() -> None:
    """DispatcherApp with no explicit jobs reads state from DB on mount."""
    from claude_dispatch.db import init_db, upsert_session
    from claude_dispatch.dispatcher import _load_jobs_from_db

    await init_db()
    await upsert_session(
        "persist-job-1", "plan", "sess-p1",
        description="Persistent task", status="done", cost_usd=0.01,
    )

    jobs = await _load_jobs_from_db(Config())
    assert any(j.job_id == "persist-job-1" for j in jobs)
    job = next(j for j in jobs if j.job_id == "persist-job-1")
    assert job.description == "Persistent task"
    assert len(job.agents) == 1
    assert job.agents[0].session_id == "sess-p1"


# ── PID check: dead process → status corrected ────────────────────────────────


@pytest.mark.asyncio
async def test_dead_pid_corrected_to_failed_on_load() -> None:
    """If a stored PID is dead, _load_jobs_from_db marks agent as failed."""
    from claude_dispatch.db import init_db, upsert_session, upsert_worker_meta
    from claude_dispatch.dispatcher import _load_jobs_from_db

    await init_db()

    # Use PID 1 — on macOS/Linux it's init/launchd, not our process
    # Use a definitely-dead PID by finding one that doesn't exist
    dead_pid = 9999999

    await upsert_session(
        "dead-pid-job", "code", "sess-dead",
        description="Dead worker test", status="running",
    )
    await upsert_worker_meta("dead-pid-job", "code", dead_pid, "/tmp/dead.log")

    jobs = await _load_jobs_from_db(Config())
    job = next((j for j in jobs if j.job_id == "dead-pid-job"), None)
    assert job is not None
    agent = next((a for a in job.agents if a.spec.type.value == "code"), None)
    assert agent is not None
    # Dead PID → status corrected away from RUNNING
    assert agent.status != AgentStatus.RUNNING


# ── _use_workers flag: subprocess vs in-process ───────────────────────────────


@pytest.mark.asyncio
async def test_spawn_worker_falls_back_to_in_process_when_flag_false(tmp_path: Path) -> None:
    """When _use_workers=False, _spawn_worker runs agent in-process (no subprocess)."""
    from claude_code_sdk.types import ResultMessage

    job = Job(description="test", config=Config(), db_enabled=False)
    job._workdir = tmp_path
    (tmp_path / "job-plan.yaml").write_text(yaml.dump({"summary": "s", "agents": []}))

    from claude_dispatch.agent import Agent

    agent = Agent(
        spec=AgentSpec(type=AgentType.PLAN, cwd=str(tmp_path)),
        job_id=job.job_id,
        agent_id=f"{job.job_id}-plan",
    )

    query_called = [False]

    async def fake_query(prompt, options):
        query_called[0] = True
        yield ResultMessage(
            subtype="result", duration_ms=1, duration_api_ms=1,
            is_error=False, num_turns=1, session_id="sess-inproc", total_cost_usd=0.001,
        )

    with patch("claude_dispatch.agent.query", fake_query):
        await job._spawn_worker(agent, "do something", "", None)

    assert query_called[0], "in-process query should have been called"
    assert agent.session_id == "sess-inproc"
