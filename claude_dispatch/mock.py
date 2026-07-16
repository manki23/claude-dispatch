"""Mock data for TUI development and testing — not used in production."""

from __future__ import annotations

import time

from claude_dispatch.agent import Agent, AgentSpec, AgentStatus, AgentType
from claude_dispatch.config import Config, Defaults
from claude_dispatch.job import Job, JobPhase, JobStatus


def make_mock_config() -> Config:
    return Config(
        repos={
            "acme-api": "~/code/acme-api",
            "acme-frontend": "~/code/acme-frontend",
            "acme-infra": "~/code/acme-infra",
        },
        defaults=Defaults(
            plan_model="claude-sonnet-4-6",
            execute_model="claude-haiku-4-5-20251001",
            max_parallel_agents=4,
            plan_timeout_s=300,
        ),
    )


def make_mock_jobs() -> list[Job]:
    cfg = make_mock_config()

    # ── Job 1: running, execute phase ────────────────────────────────────────
    # plan done → code + jira parallel → test waits on code
    # Demonstrates: send_message inbox, [user] log lines, [resuming] log lines
    j1 = Job(
        description="TICKET-101: fix session expiry bug in auth service",
        config=cfg,
        job_id="abc123",
        db_enabled=False,
    )
    j1.phase = JobPhase.EXECUTE
    j1.status = JobStatus.RUNNING
    j1.cost_usd = 0.14
    j1.created_at = time.time() - 23 * 60

    plan1 = Agent(
        spec=AgentSpec(type=AgentType.PLAN, model="claude-sonnet-4-6"),
        job_id="abc123",
        agent_id="abc123-plan",
        status=AgentStatus.DONE,
        session_id="sess-abc123-plan",
        cost_usd=0.03,
        last_action="Write(job-plan.yaml)",
        log_lines=[
            "Reading TICKET-101 description…",
            "[tool] Glob",
            "Found session_manager.py, token_store.py",
            "[tool] Read",
            "Drafting execution plan…",
            "DONE: wrote job-plan.yaml (3 agents: code, test, jira)",
        ],
    )
    code1 = Agent(
        spec=AgentSpec(
            type=AgentType.CODE,
            cwd="~/code/acme-api",
            allowed_tools=["Bash", "Read", "Edit", "Write", "Glob", "Grep"],
        ),
        job_id="abc123",
        agent_id="abc123-code",
        status=AgentStatus.RUNNING,
        session_id="sess-abc123-code",
        cost_usd=0.08,
        last_action="Edit(auth/session_manager.py)",
        log_lines=[
            "Reading auth/session_manager.py…",
            "[tool] Read",
            "Found off-by-one in token expiry calculation (line 142)",
            "[tool] Edit",
            "Running: pytest tests/test_session.py…",
            "[tool] Bash",
            "3 tests pass, 1 still failing — investigating…",
            "[user] please also check token_store.py for the same bug",
            "[resuming with queued message]",
            "[tool] Grep",
            "Found matching pattern in token_store.py line 89",
        ],
    )
    # Simulate a message already queued in the inbox (send_message in action)
    code1._inbox.put_nowait("check token_refresh_interval too")

    test1 = Agent(
        spec=AgentSpec(
            type=AgentType.TEST,
            cwd="~/code/acme-api",
            depends_on=["code"],
        ),
        job_id="abc123",
        agent_id="abc123-test",
        status=AgentStatus.WAITING,
        cost_usd=0.0,
        last_action="",
        log_lines=[],
    )
    jira1 = Agent(
        spec=AgentSpec(type=AgentType.JIRA),
        job_id="abc123",
        agent_id="abc123-jira",
        status=AgentStatus.RUNNING,
        session_id="sess-abc123-jira",
        cost_usd=0.03,
        last_action="mcp__atlassian__editJiraIssue(...)",
        log_lines=[
            "Fetching TICKET-101 details…",
            "[tool] mcp__atlassian__getJiraIssue",
            "Updating status to IN PROGRESS…",
            "[tool] mcp__atlassian__transitionJiraIssue",
            "Adding comment: 'Root cause identified — session expiry off-by-one'",
            "[tool] mcp__atlassian__addCommentToJiraIssue",
        ],
    )
    j1.agents = [plan1, code1, test1, jira1]

    # ── Job 2: running, plan phase ────────────────────────────────────────────
    j2 = Job(
        description="write API docs for /v2/users endpoint",
        config=cfg,
        job_id="def456",
        db_enabled=False,
    )
    j2.phase = JobPhase.PLAN
    j2.status = JobStatus.RUNNING
    j2.cost_usd = 0.02
    j2.created_at = time.time() - 4 * 60

    plan2 = Agent(
        spec=AgentSpec(type=AgentType.PLAN, model="claude-sonnet-4-6"),
        job_id="def456",
        agent_id="def456-plan",
        status=AgentStatus.RUNNING,
        session_id="sess-def456-plan",
        cost_usd=0.02,
        last_action="Grep('v2/users')",
        log_lines=[
            "Reading task: write API docs for /v2/users endpoint",
            "[tool] Glob",
            "Found: routes/v2/users.py, schemas/user.py",
            "[tool] Read",
            "Analysing route handlers and response schemas…",
            "[tool] Grep",
            "Mapping endpoints to OpenAPI spec…",
        ],
    )
    j2.agents = [plan2]

    # ── Job 3: done — full plan→code→test→review→jira chain ──────────────────
    # Demonstrates: review agent, all DONE statuses, complete session_id set,
    # on_agent_ready would have wired log callbacks on each of these
    j3 = Job(
        description="TICKET-88: migrate database config to env vars",
        config=cfg,
        job_id="ghi789",
        db_enabled=False,
    )
    j3.phase = JobPhase.DONE
    j3.status = JobStatus.DONE
    j3.cost_usd = 0.18
    j3.created_at = time.time() - 2 * 3600

    plan3 = Agent(
        spec=AgentSpec(type=AgentType.PLAN, model="claude-sonnet-4-6"),
        job_id="ghi789",
        agent_id="ghi789-plan",
        status=AgentStatus.DONE,
        session_id="sess-ghi789-plan",
        cost_usd=0.03,
        last_action="Write(job-plan.yaml)",
        log_lines=[
            "Reading TICKET-88…",
            "[tool] Glob",
            "Mapping 12 config keys to env vars…",
            "[tool] Read",
            "DONE: wrote job-plan.yaml (4 agents: code, test, review, jira)",
        ],
    )
    code3 = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="~/code/acme-infra"),
        job_id="ghi789",
        agent_id="ghi789-code",
        status=AgentStatus.DONE,
        session_id="sess-ghi789-code",
        cost_usd=0.07,
        last_action="Bash(git commit -m '...')",
        log_lines=[
            "Reading config/database.yaml…",
            "[tool] Read",
            "Editing config/database.yaml → referencing env vars",
            "[tool] Edit",
            "Editing .env.example → adding DB_HOST, DB_PORT, DB_NAME",
            "[tool] Edit",
            "Running: make test",
            "[tool] Bash",
            "All tests pass",
            "DONE: committed, branch ready for PR",
        ],
    )
    test3 = Agent(
        spec=AgentSpec(
            type=AgentType.TEST,
            cwd="~/code/acme-infra",
            depends_on=["code"],
        ),
        job_id="ghi789",
        agent_id="ghi789-test",
        status=AgentStatus.DONE,
        session_id="sess-ghi789-test",
        cost_usd=0.03,
        last_action="Bash(make test)",
        log_lines=[
            "Running: make test…",
            "[tool] Bash",
            "42 passed, 0 failed",
            "Running: make lint…",
            "[tool] Bash",
            "DONE: all checks green",
        ],
    )
    review3 = Agent(
        spec=AgentSpec(
            type=AgentType.REVIEW,
            cwd="~/code/acme-infra",
            depends_on=["test"],
        ),
        job_id="ghi789",
        agent_id="ghi789-review",
        status=AgentStatus.DONE,
        session_id="sess-ghi789-review",
        cost_usd=0.03,
        last_action="Glob('**/*.yaml')",
        log_lines=[
            "Reviewing diff…",
            "[tool] Glob",
            "[tool] Read",
            "No secrets hardcoded — env var references only",
            "DONE: LGTM",
        ],
    )
    jira3 = Agent(
        spec=AgentSpec(type=AgentType.JIRA),
        job_id="ghi789",
        agent_id="ghi789-jira",
        status=AgentStatus.DONE,
        session_id="sess-ghi789-jira",
        cost_usd=0.02,
        last_action="mcp__atlassian__transitionJiraIssue(...)",
        log_lines=[
            "[tool] mcp__atlassian__transitionJiraIssue",
            "Transitioned TICKET-88 → DONE",
            "[tool] mcp__atlassian__addCommentToJiraIssue",
            "DONE",
        ],
    )
    j3.agents = [plan3, code3, test3, review3, jira3]

    # ── Job 4: failed — code agent crashed ───────────────────────────────────
    # Demonstrates: AgentStatus.FAILED, [error] log lines, dependent agent WAITING
    j4 = Job(
        description="TICKET-99: refactor payment processor",
        config=cfg,
        job_id="jkl012",
        db_enabled=False,
    )
    j4.phase = JobPhase.EXECUTE
    j4.status = JobStatus.FAILED
    j4.cost_usd = 0.07
    j4.created_at = time.time() - 45 * 60

    plan4 = Agent(
        spec=AgentSpec(type=AgentType.PLAN, model="claude-sonnet-4-6"),
        job_id="jkl012",
        agent_id="jkl012-plan",
        status=AgentStatus.DONE,
        session_id="sess-jkl012-plan",
        cost_usd=0.02,
        last_action="Write(job-plan.yaml)",
        log_lines=[
            "Reading TICKET-99…",
            "[tool] Read",
            "DONE: wrote job-plan.yaml",
        ],
    )
    code4 = Agent(
        spec=AgentSpec(type=AgentType.CODE, cwd="~/code/acme-api"),
        job_id="jkl012",
        agent_id="jkl012-code",
        status=AgentStatus.FAILED,
        session_id="sess-jkl012-code",
        cost_usd=0.05,
        last_action="Bash(make build)",
        log_lines=[
            "Reading payments/processor.py…",
            "[tool] Read",
            "Refactoring charge() method…",
            "[tool] Edit",
            "Running: make build…",
            "[tool] Bash",
            "[error] compilation failed: undefined: stripe.ChargeParams",
            "[error] ProcessError: agent exited with code 1",
        ],
    )
    test4 = Agent(
        spec=AgentSpec(
            type=AgentType.TEST,
            cwd="~/code/acme-api",
            depends_on=["code"],
        ),
        job_id="jkl012",
        agent_id="jkl012-test",
        status=AgentStatus.WAITING,
        cost_usd=0.0,
        last_action="",
        log_lines=[],
    )
    j4.agents = [plan4, code4, test4]

    return [j1, j2, j3, j4]
