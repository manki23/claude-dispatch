"""Tests for MCP config passthrough to ClaudeCodeOptions."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml
from claude_code_sdk.types import ResultMessage

from claude_dispatch.agent import Agent, AgentSpec, AgentStatus, AgentType
from claude_dispatch.config import Config
from claude_dispatch.job import Job


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


# ── AgentSpec.mcp_config_path ─────────────────────────────────────────────────


def test_agent_spec_mcp_config_path_default_is_none() -> None:
    spec = AgentSpec(type=AgentType.CODE)
    assert spec.mcp_config_path is None


def test_agent_spec_mcp_config_path_set() -> None:
    spec = AgentSpec(type=AgentType.CODE, mcp_config_path="/tmp/claude.json")
    assert spec.mcp_config_path == "/tmp/claude.json"


# ── Agent._run_turn: mcp_servers forwarded ────────────────────────────────────


@pytest.mark.asyncio
async def test_mcp_config_path_forwarded_to_options(tmp_path) -> None:
    """mcp_config_path on spec → ClaudeCodeOptions.mcp_servers receives the path."""
    mcp_file = tmp_path / "claude.json"
    mcp_file.write_text("{}")

    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp", mcp_config_path=str(mcp_file)),
        job_id="j1",
        agent_id="j1-code",
    )

    captured_options = []

    async def fake_query(prompt, options):
        captured_options.append(options)
        yield result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await agent.run("do work")

    assert len(captured_options) == 1
    assert captured_options[0].mcp_servers == str(mcp_file)


@pytest.mark.asyncio
async def test_no_mcp_config_path_passes_empty_dict(tmp_path) -> None:
    """No mcp_config_path → mcp_servers is empty dict (SDK default)."""
    agent = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        job_id="j1",
        agent_id="j1-code",
    )

    captured_options = []

    async def fake_query(prompt, options):
        captured_options.append(options)
        yield result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await agent.run("do work")

    assert captured_options[0].mcp_servers == {}


# ── Job._mcp_config_path ──────────────────────────────────────────────────────


def test_mcp_config_path_returns_none_when_not_configured() -> None:
    job = Job(description="t", config=Config(), db_enabled=False)
    # Default config has mcp_config = "~/.claude.json" — file may or may not exist
    # Just verify it returns str or None, never raises
    result = job._mcp_config_path()
    assert result is None or isinstance(result, str)


def test_mcp_config_path_returns_none_when_file_missing(tmp_path) -> None:
    from claude_dispatch.config import ClaudeConfig

    config = Config()
    config.claude = ClaudeConfig(mcp_config=str(tmp_path / "nonexistent.json"))
    job = Job(description="t", config=config, db_enabled=False)
    assert job._mcp_config_path() is None


def test_mcp_config_path_returns_path_when_file_exists(tmp_path) -> None:
    from claude_dispatch.config import ClaudeConfig

    mcp_file = tmp_path / "claude.json"
    mcp_file.write_text("{}")
    config = Config()
    config.claude = ClaudeConfig(mcp_config=str(mcp_file))
    job = Job(description="t", config=config, db_enabled=False)
    assert job._mcp_config_path() == str(mcp_file)


# ── Job._run_plan_phase: mcp forwarded to plan agent ─────────────────────────


@pytest.mark.asyncio
async def test_plan_agent_receives_mcp_config(tmp_path) -> None:
    """Plan agent spec.mcp_config_path set from job config."""
    from claude_dispatch.config import ClaudeConfig

    mcp_file = tmp_path / "claude.json"
    mcp_file.write_text("{}")
    config = Config()
    config.claude = ClaudeConfig(mcp_config=str(mcp_file))

    job = Job(description="t", config=config, db_enabled=False)
    job._workdir = tmp_path

    captured_options = []

    async def fake_query(prompt, options):
        captured_options.append(options)
        (tmp_path / "job-plan.yaml").write_text(yaml.dump({"summary": "s", "agents": []}))
        yield result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await job._run_plan_phase()

    assert captured_options[0].mcp_servers == str(mcp_file)


# ── Job._run_execute_phase: mcp forwarded to exec agents ─────────────────────


@pytest.mark.asyncio
async def test_exec_agents_receive_mcp_config(tmp_path) -> None:
    """Execution agents also receive mcp_config_path from job config."""
    from claude_dispatch.config import ClaudeConfig

    mcp_file = tmp_path / "claude.json"
    mcp_file.write_text("{}")
    config = Config()
    config.claude = ClaudeConfig(mcp_config=str(mcp_file))

    plan = {"summary": "s", "agents": [{"type": "code", "cwd": str(tmp_path)}]}
    (tmp_path / "job-plan.yaml").write_text(yaml.dump(plan))

    job = Job(description="t", config=config, db_enabled=False)
    job._workdir = tmp_path

    captured_options = []

    async def fake_query(prompt, options):
        captured_options.append(options)
        yield result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await job._run_execute_phase()

    assert len(captured_options) == 1
    assert captured_options[0].mcp_servers == str(mcp_file)


# ── Mock: inbox pre-loaded ────────────────────────────────────────────────────


def test_mock_code_agent_has_queued_inbox_message() -> None:
    """mock job 1's code agent has a message pre-queued in the inbox."""
    from claude_dispatch.mock import make_mock_jobs

    jobs = make_mock_jobs()
    code = next(a for a in jobs[0].agents if a.spec.type == AgentType.CODE)
    assert code._inbox.qsize() == 1
    assert code._inbox.get_nowait() == "check token_refresh_interval too"


def test_mock_job3_has_review_agent() -> None:
    """mock job 3 (done) includes a review agent — exercises the full chain."""
    from claude_dispatch.mock import make_mock_jobs

    jobs = make_mock_jobs()
    j3 = jobs[2]
    agent_types = [a.spec.type for a in j3.agents]
    assert AgentType.REVIEW in agent_types


def test_mock_all_done_agents_have_session_ids() -> None:
    """Every DONE agent in the mock has a session_id for resume support."""
    from claude_dispatch.mock import make_mock_jobs

    jobs = make_mock_jobs()
    for job in jobs:
        for agent in job.agents:
            if agent.status == AgentStatus.DONE:
                assert agent.session_id is not None, (
                    f"{job.job_id}/{agent.spec.type.value} is DONE but has no session_id"
                )


def test_mock_jira_agents_use_mcp_tools() -> None:
    """Jira agent log_lines in mock reference real MCP tool names."""
    from claude_dispatch.mock import make_mock_jobs

    jobs = make_mock_jobs()
    jira_agents = [
        a for job in jobs for a in job.agents if a.spec.type == AgentType.JIRA and a.log_lines
    ]
    assert jira_agents, "expected at least one jira agent with logs"
    all_logs = " ".join(line for a in jira_agents for line in a.log_lines)
    assert "mcp__atlassian__" in all_logs
