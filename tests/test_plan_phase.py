"""Tests for Job plan phase — SDK call, timeout, missing plan file."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from claude_code_sdk.types import AssistantMessage, ResultMessage, TextBlock

from claude_dispatch.agent import AgentStatus
from claude_dispatch.config import Config, Defaults
from claude_dispatch.job import Job, JobPhase


def make_job(description: str = "Add unit tests", plan_timeout_s: int = 10) -> Job:
    config = Config(defaults=Defaults(plan_timeout_s=plan_timeout_s))
    return Job(description=description, config=config, db_enabled=False)


def _result_msg(session_id: str = "sess-plan", is_error: bool = False) -> ResultMessage:
    return ResultMessage(
        subtype="result",
        duration_ms=100,
        duration_api_ms=80,
        is_error=is_error,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=0.01,
    )


def _minimal_plan_yaml() -> dict:
    return {
        "summary": "Add unit tests for the foo module",
        "agents": [
            {"type": "test", "cwd": "/tmp/test-worktree"},
        ],
    }


# ── happy path ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_phase_writes_plan_file(tmp_path: Path) -> None:
    """Plan agent writes job-plan.yaml → phase transitions to EXECUTE."""
    job = make_job()
    # Redirect workdir to tmp_path so plan_path lands somewhere writable
    job._workdir = tmp_path

    plan_content = yaml.dump(_minimal_plan_yaml())

    async def fake_query(prompt, options):
        # Simulate agent writing the plan file mid-stream
        (tmp_path / "job-plan.yaml").write_text(plan_content)
        yield AssistantMessage(content=[TextBlock(text="Plan written.")], model="claude-sonnet-4-6")
        yield _result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await job._run_plan_phase()

    assert job.phase == JobPhase.PLAN  # phase stays PLAN until run() advances it
    plan_agent = job.agents[0]
    assert plan_agent.status == AgentStatus.DONE
    assert plan_agent.spec.model == "claude-sonnet-4-6"
    assert job.plan_path.exists()


@pytest.mark.asyncio
async def test_plan_phase_accumulates_cost(tmp_path: Path) -> None:
    job = make_job()
    job._workdir = tmp_path

    async def fake_query(prompt, options):
        (tmp_path / "job-plan.yaml").write_text(yaml.dump(_minimal_plan_yaml()))
        yield _result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await job._run_plan_phase()

    assert job.cost_usd == pytest.approx(0.01)


# ── failure cases ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_phase_raises_if_file_missing(tmp_path: Path) -> None:
    """Agent finishes but never writes the plan file → RuntimeError."""
    job = make_job()
    job._workdir = tmp_path

    async def fake_query(prompt, options):
        yield _result_msg()  # no file written

    with patch("claude_dispatch.agent.query", fake_query):
        with pytest.raises(RuntimeError, match="was not written"):
            await job._run_plan_phase()

    assert job.agents[0].status == AgentStatus.FAILED


@pytest.mark.asyncio
async def test_plan_phase_raises_on_sdk_error(tmp_path: Path) -> None:
    """ResultMessage with is_error=True → agent FAILED → RuntimeError from missing file."""
    job = make_job()
    job._workdir = tmp_path

    async def fake_query(prompt, options):
        yield _result_msg(is_error=True)

    with patch("claude_dispatch.agent.query", fake_query):
        with pytest.raises(RuntimeError, match="was not written"):
            await job._run_plan_phase()

    assert job.agents[0].status == AgentStatus.FAILED


@pytest.mark.asyncio
async def test_plan_phase_timeout(tmp_path: Path) -> None:
    """Plan agent hangs past timeout → RuntimeError(timed out)."""
    job = make_job(plan_timeout_s=1)
    job._workdir = tmp_path

    async def fake_query(prompt, options):
        await asyncio.sleep(10)  # hangs forever relative to 1s timeout
        yield _result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        with pytest.raises(RuntimeError, match="timed out"):
            await job._run_plan_phase()

    assert job.agents[0].status == AgentStatus.FAILED


# ── system prompt / options wiring ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_phase_passes_system_prompt(tmp_path: Path) -> None:
    """Verify ClaudeCodeOptions receives the PLAN_SYSTEM_PROMPT."""
    from claude_dispatch.prompts import PLAN_SYSTEM_PROMPT

    job = make_job()
    job._workdir = tmp_path
    captured_options = []

    async def fake_query(prompt, options):
        captured_options.append(options)
        (tmp_path / "job-plan.yaml").write_text(yaml.dump(_minimal_plan_yaml()))
        yield _result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await job._run_plan_phase()

    assert len(captured_options) == 1
    assert captured_options[0].system_prompt == PLAN_SYSTEM_PROMPT
    assert captured_options[0].permission_mode == "bypassPermissions"


@pytest.mark.asyncio
async def test_plan_phase_passes_description_in_prompt(tmp_path: Path) -> None:
    """Verify the job description appears in the prompt passed to query()."""
    job = make_job(description="Refactor the auth module")
    job._workdir = tmp_path
    captured_prompts = []

    async def fake_query(prompt, options):
        captured_prompts.append(prompt)
        (tmp_path / "job-plan.yaml").write_text(yaml.dump(_minimal_plan_yaml()))
        yield _result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await job._run_plan_phase()

    assert "Refactor the auth module" in captured_prompts[0]
    assert str(tmp_path / "job-plan.yaml") in captured_prompts[0]
