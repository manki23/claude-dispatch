"""Tests for hooks.py — fire(), payload builders, and Job wiring."""

from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from claude_dispatch.hooks import (
    POST_AGENT_DONE,
    POST_JOB_DONE,
    POST_JOB_FAILED,
    PRE_JOB_START,
    fire,
    post_agent_done_payload,
    post_job_done_payload,
    pre_job_start_payload,
)
from claude_dispatch.job import Job
from claude_dispatch.config import Config
from claude_code_sdk.types import ResultMessage


# ── helpers ───────────────────────────────────────────────────────────────────


def make_executable_hook(hooks_dir: Path, name: str, script: str) -> Path:
    """Write a shell script hook and make it executable."""
    path = hooks_dir / name
    path.write_text(script)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return path


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


# ── payload builders ──────────────────────────────────────────────────────────


def test_pre_job_start_payload() -> None:
    p = pre_job_start_payload("job1", "Fix the login bug")
    assert p == {"event": PRE_JOB_START, "job_id": "job1", "description": "Fix the login bug"}


def test_post_agent_done_payload() -> None:
    p = post_agent_done_payload("job1", "code", "done", "sess-x", 0.03, "Fix bug")
    assert p["event"] == POST_AGENT_DONE
    assert p["agent_type"] == "code"
    assert p["status"] == "done"
    assert p["session_id"] == "sess-x"
    assert p["cost_usd"] == pytest.approx(0.03)


def test_post_job_done_payload_status_done() -> None:
    p = post_job_done_payload("job1", "desc", "done", 0.1, [])
    assert p["event"] == POST_JOB_DONE
    assert p["status"] == "done"


def test_post_job_done_payload_status_failed() -> None:
    p = post_job_done_payload("job1", "desc", "failed", 0.1, [])
    assert p["event"] == POST_JOB_FAILED
    assert p["status"] == "failed"


# ── fire() — discovery ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fire_skips_if_disabled(tmp_path: Path) -> None:
    """enabled=False → hook never called even if file exists."""
    hook = make_executable_hook(tmp_path, "pre_job_start", "#!/bin/sh\nexit 0\n")
    # If fire respects enabled=False, the proc is never created
    with patch("claude_dispatch.hooks.asyncio.create_subprocess_exec") as mock_exec:
        await fire(PRE_JOB_START, {}, hooks_dir=tmp_path, enabled=False)
    mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_fire_skips_if_hook_not_found(tmp_path: Path) -> None:
    """No hook file → silently returns."""
    with patch("claude_dispatch.hooks.asyncio.create_subprocess_exec") as mock_exec:
        await fire(PRE_JOB_START, {}, hooks_dir=tmp_path, enabled=True)
    mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_fire_skips_non_executable(tmp_path: Path) -> None:
    """File exists but not executable → warning logged, not executed."""
    path = tmp_path / PRE_JOB_START
    path.write_text("#!/bin/sh\nexit 0\n")
    # Not executable (default write permissions)
    path.chmod(0o644)

    with patch("claude_dispatch.hooks.asyncio.create_subprocess_exec") as mock_exec:
        await fire(PRE_JOB_START, {}, hooks_dir=tmp_path, enabled=True)
    mock_exec.assert_not_called()


# ── fire() — execution ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fire_passes_payload_via_stdin(tmp_path: Path) -> None:
    """Hook receives JSON payload on stdin; captured in an output file."""
    out = tmp_path / "received.json"
    script = f"#!/bin/sh\ncat > {out}\n"
    make_executable_hook(tmp_path, PRE_JOB_START, script)

    payload = {"event": PRE_JOB_START, "job_id": "j1", "description": "test"}
    await fire(PRE_JOB_START, payload, hooks_dir=tmp_path, enabled=True)

    received = json.loads(out.read_text())
    assert received == payload


@pytest.mark.asyncio
async def test_fire_nonzero_exit_does_not_raise(tmp_path: Path) -> None:
    """Hook exits with non-zero code → warning logged, no exception."""
    make_executable_hook(tmp_path, PRE_JOB_START, "#!/bin/sh\nexit 1\n")
    # Must not raise
    await fire(PRE_JOB_START, {}, hooks_dir=tmp_path, enabled=True)


@pytest.mark.asyncio
async def test_fire_timeout_does_not_raise(tmp_path: Path) -> None:
    """Hook hangs past 30s → TimeoutError caught, no exception propagates."""
    make_executable_hook(tmp_path, PRE_JOB_START, "#!/bin/sh\nsleep 60\n")

    with patch("claude_dispatch.hooks.asyncio.wait_for", side_effect=asyncio.TimeoutError):
        await fire(PRE_JOB_START, {}, hooks_dir=tmp_path, enabled=True)


@pytest.mark.asyncio
async def test_fire_unexpected_exception_does_not_raise(tmp_path: Path) -> None:
    """Unexpected error in subprocess setup → swallowed."""
    make_executable_hook(tmp_path, PRE_JOB_START, "#!/bin/sh\nexit 0\n")

    with patch(
        "claude_dispatch.hooks.asyncio.create_subprocess_exec",
        side_effect=OSError("no such file"),
    ):
        await fire(PRE_JOB_START, {}, hooks_dir=tmp_path, enabled=True)


# ── Job hook wiring ───────────────────────────────────────────────────────────


def make_job(hooks_dir: Path) -> Job:
    config = Config()
    job = Job(
        description="Add tests for auth module",
        config=config,
        db_enabled=False,
        hooks_dir=hooks_dir,
    )
    return job


@pytest.mark.asyncio
async def test_job_run_fires_pre_job_start(tmp_path: Path) -> None:
    job = make_job(tmp_path)
    job._workdir = tmp_path
    fired: list[str] = []

    async def fake_fire(name, payload, *, hooks_dir=None, enabled=None):
        fired.append(name)

    plan_content = yaml.dump({"summary": "s", "agents": []})

    async def fake_query(prompt, options):
        (tmp_path / "job-plan.yaml").write_text(plan_content)
        yield result_msg()

    with (
        patch("claude_dispatch.agent.query", fake_query),
        patch("claude_dispatch.job.fire", fake_fire),
    ):
        await job.run()

    assert fired[0] == PRE_JOB_START


@pytest.mark.asyncio
async def test_job_run_fires_post_job_done(tmp_path: Path) -> None:
    job = make_job(tmp_path)
    job._workdir = tmp_path
    fired: list[str] = []

    async def fake_fire(name, payload, *, hooks_dir=None, enabled=None):
        fired.append(name)

    plan_content = yaml.dump({"summary": "s", "agents": []})

    async def fake_query(prompt, options):
        (tmp_path / "job-plan.yaml").write_text(plan_content)
        yield result_msg()

    with (
        patch("claude_dispatch.agent.query", fake_query),
        patch("claude_dispatch.job.fire", fake_fire),
    ):
        await job.run()

    assert POST_JOB_DONE in fired


@pytest.mark.asyncio
async def test_job_run_fires_post_job_failed_on_error(tmp_path: Path) -> None:
    job = make_job(tmp_path)
    job._workdir = tmp_path
    fired: list[str] = []

    async def fake_fire(name, payload, *, hooks_dir=None, enabled=None):
        fired.append(name)

    # Plan agent never writes the file → RuntimeError → post_job_failed
    async def fake_query(prompt, options):
        yield result_msg()

    with (
        patch("claude_dispatch.agent.query", fake_query),
        patch("claude_dispatch.job.fire", fake_fire),
    ):
        with pytest.raises(RuntimeError):
            await job.run()

    assert POST_JOB_FAILED in fired


@pytest.mark.asyncio
async def test_plan_phase_fires_post_agent_done(tmp_path: Path) -> None:
    job = make_job(tmp_path)
    job._workdir = tmp_path
    fired: list[tuple[str, dict]] = []

    async def fake_fire(name, payload, *, hooks_dir=None, enabled=None):
        fired.append((name, payload))

    plan_content = yaml.dump({"summary": "s", "agents": []})

    async def fake_query(prompt, options):
        (tmp_path / "job-plan.yaml").write_text(plan_content)
        yield result_msg("sess-plan")

    with (
        patch("claude_dispatch.agent.query", fake_query),
        patch("claude_dispatch.job.fire", fake_fire),
    ):
        await job._run_plan_phase()

    agent_done_calls = [(n, p) for n, p in fired if n == POST_AGENT_DONE]
    assert len(agent_done_calls) == 1
    _, payload = agent_done_calls[0]
    assert payload["agent_type"] == "plan"
    assert payload["session_id"] == "sess-plan"
    assert payload["job_id"] == job.job_id


@pytest.mark.asyncio
async def test_execute_phase_fires_post_agent_done_for_each_agent(tmp_path: Path) -> None:
    plan = {
        "summary": "s",
        "agents": [
            {"type": "code", "cwd": str(tmp_path)},
            {"type": "test", "cwd": str(tmp_path), "depends_on": ["code"]},
        ],
    }
    (tmp_path / "job-plan.yaml").write_text(yaml.dump(plan))

    job = make_job(tmp_path)
    job._workdir = tmp_path
    fired_agent_done: list[str] = []

    async def fake_fire(name, payload, *, hooks_dir=None, enabled=None):
        if name == POST_AGENT_DONE:
            fired_agent_done.append(payload["agent_type"])

    async def fake_query(prompt, options):
        yield result_msg()

    with (
        patch("claude_dispatch.agent.query", fake_query),
        patch("claude_dispatch.job.fire", fake_fire),
    ):
        await job._run_execute_phase()

    assert set(fired_agent_done) == {"code", "test"}


@pytest.mark.asyncio
async def test_post_agent_done_payload_content(tmp_path: Path) -> None:
    job = make_job(tmp_path)
    job._workdir = tmp_path
    payloads: list[dict] = []

    async def fake_fire(name, payload, *, hooks_dir=None, enabled=None):
        if name == POST_AGENT_DONE:
            payloads.append(payload)

    plan_content = yaml.dump({"summary": "s", "agents": []})

    async def fake_query(prompt, options):
        (tmp_path / "job-plan.yaml").write_text(plan_content)
        yield result_msg("sess-xyz")

    with (
        patch("claude_dispatch.agent.query", fake_query),
        patch("claude_dispatch.job.fire", fake_fire),
    ):
        await job._run_plan_phase()

    assert len(payloads) == 1
    p = payloads[0]
    assert p["event"] == POST_AGENT_DONE
    assert p["agent_type"] == "plan"
    assert p["session_id"] == "sess-xyz"
    assert p["description"] == "Add tests for auth module"
    assert p["status"] == "done"
