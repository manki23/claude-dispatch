"""Tests for plan.py — parse_plan() robustness and validate_plan() checks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from claude_code_sdk.types import ResultMessage

from claude_dispatch.agent import AgentSpec, AgentType
from claude_dispatch.config import Config
from claude_dispatch.job import Job
from claude_dispatch.plan import (
    JobPlan,
    PlanValidationError,
    WorktreeSpec,
    parse_plan,
    validate_plan,
)

# ── parse_plan: happy path ────────────────────────────────────────────────────


def test_parse_plan_minimal(tmp_path: Path) -> None:
    (tmp_path / "plan.yaml").write_text(yaml.dump({"summary": "s", "agents": []}))
    plan = parse_plan(tmp_path / "plan.yaml")
    assert plan.summary == "s"
    assert plan.agents == []
    assert plan.worktrees == []


def test_parse_plan_full(tmp_path: Path) -> None:
    raw = {
        "summary": "Refactor auth",
        "agents": [
            {"type": "code", "cwd": "/tmp/wt", "allowed_tools": ["Bash"], "depends_on": []},
            {"type": "test", "cwd": "/tmp/wt", "depends_on": ["code"]},
        ],
        "resources": {
            "worktrees": [{"repo": "acme-api", "path": "/tmp/wt", "branch": "fix/auth"}]
        },
    }
    (tmp_path / "plan.yaml").write_text(yaml.dump(raw))
    plan = parse_plan(tmp_path / "plan.yaml")

    assert plan.summary == "Refactor auth"
    assert len(plan.agents) == 2
    assert plan.agents[0].type == AgentType.CODE
    assert plan.agents[1].depends_on == ["code"]
    assert len(plan.worktrees) == 1
    assert plan.worktrees[0].repo == "acme-api"


def test_parse_plan_missing_optional_fields(tmp_path: Path) -> None:
    """model, allowed_tools, depends_on are all optional."""
    (tmp_path / "plan.yaml").write_text(yaml.dump({"agents": [{"type": "jira"}]}))
    plan = parse_plan(tmp_path / "plan.yaml")
    assert plan.agents[0].model is None
    assert plan.agents[0].allowed_tools == []
    assert plan.agents[0].depends_on == []


# ── parse_plan: error cases ───────────────────────────────────────────────────


def test_parse_plan_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        parse_plan(tmp_path / "missing.yaml")


def test_parse_plan_not_a_mapping(tmp_path: Path) -> None:
    (tmp_path / "plan.yaml").write_text("- just a list\n")
    with pytest.raises(PlanValidationError, match="must be a YAML mapping"):
        parse_plan(tmp_path / "plan.yaml")


def test_parse_plan_unknown_agent_type(tmp_path: Path) -> None:
    (tmp_path / "plan.yaml").write_text(
        yaml.dump({"agents": [{"type": "hacker"}]})
    )
    with pytest.raises(PlanValidationError) as exc_info:
        parse_plan(tmp_path / "plan.yaml")
    assert "unknown type 'hacker'" in str(exc_info.value)


def test_parse_plan_agent_not_a_mapping(tmp_path: Path) -> None:
    (tmp_path / "plan.yaml").write_text(yaml.dump({"agents": ["just a string"]}))
    with pytest.raises(PlanValidationError, match="must be a mapping"):
        parse_plan(tmp_path / "plan.yaml")


def test_parse_plan_worktree_missing_fields(tmp_path: Path) -> None:
    raw = {"resources": {"worktrees": [{"repo": "acme", "path": "/tmp"}]}}  # no branch
    (tmp_path / "plan.yaml").write_text(yaml.dump(raw))
    with pytest.raises(PlanValidationError, match="missing required field"):
        parse_plan(tmp_path / "plan.yaml")


def test_parse_plan_multiple_errors_reported_together(tmp_path: Path) -> None:
    """Two bad agent entries → both errors surface at once."""
    raw = {
        "agents": [
            {"type": "bad1"},
            {"type": "bad2"},
        ]
    }
    (tmp_path / "plan.yaml").write_text(yaml.dump(raw))
    with pytest.raises(PlanValidationError) as exc_info:
        parse_plan(tmp_path / "plan.yaml")
    assert len(exc_info.value.errors) == 2


def test_parse_plan_empty_yaml(tmp_path: Path) -> None:
    """Empty file is treated as empty plan (not an error)."""
    (tmp_path / "plan.yaml").write_text("")
    plan = parse_plan(tmp_path / "plan.yaml")
    assert plan.agents == []


# ── validate_plan: happy path ─────────────────────────────────────────────────


def make_plan(agents=None, worktrees=None, summary="s") -> JobPlan:
    return JobPlan(
        agents=agents or [],
        worktrees=worktrees or [],
        summary=summary,
    )


def test_validate_plan_empty_is_valid() -> None:
    validate_plan(make_plan())  # must not raise


def test_validate_plan_valid_with_deps() -> None:
    plan = make_plan(agents=[
        AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        AgentSpec(type=AgentType.TEST, cwd="/tmp", depends_on=["code"]),
    ])
    validate_plan(plan)  # must not raise


def test_validate_plan_jira_no_cwd_is_valid() -> None:
    """jira/slack/plan don't require cwd."""
    plan = make_plan(agents=[AgentSpec(type=AgentType.JIRA)])
    validate_plan(plan)


# ── validate_plan: check 1 — duplicate agent types ───────────────────────────


def test_validate_plan_duplicate_agent_type() -> None:
    plan = make_plan(agents=[
        AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        AgentSpec(type=AgentType.CODE, cwd="/tmp/other"),
    ])
    with pytest.raises(PlanValidationError, match="Duplicate agent type: 'code'"):
        validate_plan(plan)


# ── validate_plan: check 2 — plan agent in execution list ────────────────────


def test_validate_plan_rejects_plan_agent_in_execution_list() -> None:
    plan = make_plan(agents=[AgentSpec(type=AgentType.PLAN)])
    with pytest.raises(PlanValidationError, match="'plan' must not appear"):
        validate_plan(plan)


# ── validate_plan: check 3 — cwd required ────────────────────────────────────


@pytest.mark.parametrize("agent_type", [AgentType.CODE, AgentType.TEST, AgentType.REVIEW])
def test_validate_plan_cwd_required(agent_type: AgentType) -> None:
    plan = make_plan(agents=[AgentSpec(type=agent_type)])  # no cwd
    with pytest.raises(PlanValidationError, match="requires a 'cwd'"):
        validate_plan(plan)


def test_validate_plan_cwd_with_value_is_ok() -> None:
    plan = make_plan(agents=[AgentSpec(type=AgentType.CODE, cwd="/tmp/wt")])
    validate_plan(plan)  # must not raise


# ── validate_plan: check 4 — unknown depends_on ──────────────────────────────


def test_validate_plan_unknown_dep() -> None:
    plan = make_plan(agents=[
        AgentSpec(type=AgentType.TEST, cwd="/tmp", depends_on=["code"]),  # code not in plan
    ])
    with pytest.raises(PlanValidationError, match="depends_on unknown type 'code'"):
        validate_plan(plan)


# ── validate_plan: check 5 — cycles ──────────────────────────────────────────


def test_validate_plan_cycle_two_agents() -> None:
    plan = make_plan(agents=[
        AgentSpec(type=AgentType.CODE, cwd="/tmp", depends_on=["test"]),
        AgentSpec(type=AgentType.TEST, cwd="/tmp", depends_on=["code"]),
    ])
    with pytest.raises(PlanValidationError, match="Cycle"):
        validate_plan(plan)


def test_validate_plan_self_dependency_is_cycle() -> None:
    plan = make_plan(agents=[
        AgentSpec(type=AgentType.CODE, cwd="/tmp", depends_on=["code"]),
    ])
    with pytest.raises(PlanValidationError, match="Cycle"):
        validate_plan(plan)


def test_validate_plan_chain_no_cycle() -> None:
    plan = make_plan(agents=[
        AgentSpec(type=AgentType.CODE, cwd="/tmp"),
        AgentSpec(type=AgentType.TEST, cwd="/tmp", depends_on=["code"]),
        AgentSpec(type=AgentType.REVIEW, cwd="/tmp", depends_on=["test"]),
    ])
    validate_plan(plan)  # A→B→C is not a cycle


# ── validate_plan: check 6 — worktree repo in config ─────────────────────────


def test_validate_plan_unknown_worktree_repo() -> None:
    config = Config(repos={"acme-api": "~/code/acme-api"})
    plan = make_plan(worktrees=[WorktreeSpec(repo="unknown-repo", path="/tmp/wt", branch="feat")])
    with pytest.raises(PlanValidationError, match="not in config.repos"):
        validate_plan(plan, config)


def test_validate_plan_known_worktree_repo_is_ok() -> None:
    config = Config(repos={"acme-api": "~/code/acme-api"})
    plan = make_plan(worktrees=[WorktreeSpec(repo="acme-api", path="/tmp/wt", branch="feat")])
    validate_plan(plan, config)  # must not raise


def test_validate_plan_no_config_skips_repo_check() -> None:
    """Without config, repo check is skipped entirely."""
    plan = make_plan(worktrees=[WorktreeSpec(repo="anything", path="/tmp", branch="b")])
    validate_plan(plan, config=None)  # must not raise


def test_validate_plan_empty_config_repos_skips_check() -> None:
    """If config.repos is empty, repo check is skipped."""
    config = Config(repos={})
    plan = make_plan(worktrees=[WorktreeSpec(repo="anything", path="/tmp", branch="b")])
    validate_plan(plan, config)  # must not raise


# ── all errors reported together ─────────────────────────────────────────────


def test_validate_plan_multiple_errors_collected() -> None:
    """cwd missing + unknown dep → both errors in one raise."""
    plan = make_plan(agents=[
        AgentSpec(type=AgentType.CODE),  # missing cwd
        AgentSpec(type=AgentType.TEST, cwd="/tmp", depends_on=["review"]),  # review not in plan
    ])
    with pytest.raises(PlanValidationError) as exc_info:
        validate_plan(plan)
    assert len(exc_info.value.errors) == 2


# ── integration: validate_plan called from execute phase ──────────────────────


def result_msg() -> ResultMessage:
    return ResultMessage(
        subtype="result", duration_ms=50, duration_api_ms=40,
        is_error=False, num_turns=1, session_id="sess-1", total_cost_usd=0.001,
    )


@pytest.mark.asyncio
async def test_execute_phase_raises_on_invalid_plan(tmp_path: Path) -> None:
    """Bad plan (missing cwd) → PlanValidationError raised before any agent starts."""
    bad_plan = {"summary": "s", "agents": [{"type": "code"}]}  # no cwd
    (tmp_path / "job-plan.yaml").write_text(yaml.dump(bad_plan))

    job = Job(description="test", config=Config(), db_enabled=False)
    job._workdir = tmp_path

    with pytest.raises(PlanValidationError, match="requires a 'cwd'"):
        await job._run_execute_phase()


@pytest.mark.asyncio
async def test_execute_phase_no_agents_started_before_validation(tmp_path: Path) -> None:
    """validate_plan fails → no agents appended to job.agents."""
    bad_plan = {"summary": "s", "agents": [{"type": "code"}]}  # no cwd
    (tmp_path / "job-plan.yaml").write_text(yaml.dump(bad_plan))

    job = Job(description="test", config=Config(), db_enabled=False)
    job._workdir = tmp_path

    with pytest.raises(PlanValidationError):
        await job._run_execute_phase()

    assert job.agents == []


@pytest.mark.asyncio
async def test_execute_phase_valid_plan_proceeds(tmp_path: Path) -> None:
    """Valid plan passes validation and agents run normally."""
    plan = {"summary": "s", "agents": [{"type": "code", "cwd": str(tmp_path)}]}
    (tmp_path / "job-plan.yaml").write_text(yaml.dump(plan))

    job = Job(description="test", config=Config(), db_enabled=False)
    job._workdir = tmp_path

    async def fake_query(prompt, options):
        yield result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await job._run_execute_phase()

    assert len(job.agents) == 1
