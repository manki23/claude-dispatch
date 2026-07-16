"""Mock data for TUI development and testing — not used in production."""

from __future__ import annotations

import time

from claude_dispatch.agent import Agent, AgentSpec, AgentStatus, AgentType
from claude_dispatch.config import Config
from claude_dispatch.job import Job, JobPhase, JobStatus


def make_mock_config() -> Config:
    return Config(
        repos={
            "my-repo": "~/code/my-repo",
            "my-other-repo": "~/code/my-other-repo",
        }
    )


def make_mock_jobs() -> list[Job]:
    cfg = make_mock_config()

    # Job 1 — running, execute phase, 4 agents
    j1 = Job(description="TICKET-123: fix auth bug", config=cfg, job_id="abc123")
    j1.phase = JobPhase.EXECUTE
    j1.status = JobStatus.RUNNING
    j1.cost_usd = 0.09
    j1.created_at = time.time() - 23 * 60

    plan1 = Agent(
        spec=AgentSpec(type=AgentType.PLAN),
        job_id="abc123", agent_id="abc123-plan",
        status=AgentStatus.DONE, cost_usd=0.02,
        last_action="Produced job-plan.yaml",
        log_lines=["Reading TICKET-123...", "Analysing codebase...", "Writing job-plan.yaml ✓"],
    )
    code1 = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="~/code/my-repo"),
        job_id="abc123", agent_id="abc123-code",
        status=AgentStatus.RUNNING, cost_usd=0.05,
        last_action="Editing auth/handler.go",
        log_lines=["Reading auth/handler.go...", "Editing auth/handler.go...", "Running tests..."],
    )
    jira1 = Agent(
        spec=AgentSpec(type=AgentType.JIRA),
        job_id="abc123", agent_id="abc123-jira",
        status=AgentStatus.WAITING, cost_usd=0.0,
        last_action="",
        log_lines=[],
    )
    test1 = Agent(
        spec=AgentSpec(type=AgentType.TEST, cwd="~/code/my-repo"),
        job_id="abc123", agent_id="abc123-test",
        status=AgentStatus.WAITING, cost_usd=0.0,
        last_action="",
        log_lines=[],
    )
    j1.agents = [plan1, code1, jira1, test1]

    # Job 2 — running, plan phase, 1 agent
    j2 = Job(description="write-confluence-doc: V0 improvement plan", config=cfg, job_id="def456")
    j2.phase = JobPhase.PLAN
    j2.status = JobStatus.RUNNING
    j2.cost_usd = 0.03
    j2.created_at = time.time() - 4 * 60

    plan2 = Agent(
        spec=AgentSpec(type=AgentType.PLAN),
        job_id="def456", agent_id="def456-plan",
        status=AgentStatus.RUNNING, cost_usd=0.03,
        last_action="Reading Confluence docs...",
        log_lines=[
            "Fetching Confluence pages...",
            "Reading evaluation report...",
            "Analysing LLMObs experiment data...",
        ],
    )
    j2.agents = [plan2]

    # Job 3 — done, all agents complete
    j3 = Job(description="TICKET-456: update staging config", config=cfg, job_id="ghi789")
    j3.phase = JobPhase.DONE
    j3.status = JobStatus.DONE
    j3.cost_usd = 0.02
    j3.created_at = time.time() - 2 * 3600

    plan3 = Agent(
        spec=AgentSpec(type=AgentType.PLAN),
        job_id="ghi789", agent_id="ghi789-plan",
        status=AgentStatus.DONE, cost_usd=0.01,
        last_action="Produced job-plan.yaml",
        log_lines=["Reading TICKET-456...", "Writing job-plan.yaml ✓"],
    )
    code3 = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="~/code/my-other-repo"),
        job_id="ghi789", agent_id="ghi789-code",
        status=AgentStatus.DONE, cost_usd=0.01,
        last_action="Committed changes",
        log_lines=["Editing config.yaml...", "Running tests... ✓", "Committed ✓"],
    )
    j3.agents = [plan3, code3]

    return [j1, j2, j3]
