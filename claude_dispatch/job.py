"""Job — lifecycle manager for a single human task."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from claude_dispatch.agent import Agent, AgentSpec, AgentStatus, AgentType
from claude_dispatch.config import Config
from claude_dispatch.cost_guard import CostGuard, CostLimitExceeded
from claude_dispatch.db import get_session, upsert_session
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
from claude_dispatch.prompts import (
    EXECUTION_SYSTEM_PROMPT,
    PLAN_SYSTEM_PROMPT,
    build_execution_prompt,
    build_plan_prompt,
)

logger = logging.getLogger(__name__)


class JobPhase(str, Enum):
    PLAN = "plan"
    EXECUTE = "execute"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"


class JobStatus(str, Enum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    KILLED = "killed"


@dataclass
class Job:
    """Runtime state of a Job (one per human task)."""

    description: str
    config: Config
    job_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    phase: JobPhase = field(default=JobPhase.PLAN)
    status: JobStatus = field(default=JobStatus.RUNNING)
    agents: list[Agent] = field(default_factory=list)
    cost_usd: float = 0.0
    created_at: float = field(default_factory=time.time)
    db_enabled: bool = True  # set False in tests that don't want real DB I/O
    hooks_dir: Path | None = None  # override hooks directory (useful in tests)
    on_agent_ready: Callable[[Agent], None] | None = field(default=None, repr=False)
    _workdir: Path | None = field(default=None, init=False, repr=False)

    @property
    def workdir(self) -> Path:
        """Temporary working directory for this job (plan output, scratch files)."""
        if self._workdir is None:
            self._workdir = Path(f"/tmp/claude-dispatch/{self.job_id}")
            self._workdir.mkdir(parents=True, exist_ok=True)
        return self._workdir

    @property
    def plan_path(self) -> Path:
        return self.workdir / "job-plan.yaml"

    @property
    def agent_count(self) -> str:
        running = sum(1 for a in self.agents if a.status == AgentStatus.RUNNING)
        total = len(self.agents)
        return f"{running}/{total}"

    # ── DB helpers (never raise — DB errors must not crash the job) ──────────

    async def _db_upsert(self, agent: Agent) -> None:
        if not self.db_enabled or agent.session_id is None:
            return
        try:
            await upsert_session(
                job_id=self.job_id,
                agent_type=agent.spec.type.value,
                session_id=agent.session_id,
                description=self.description,
                status=agent.status.value,
                cost_usd=agent.cost_usd,
            )
        except Exception:
            logger.exception("db upsert failed for agent %s", agent.agent_id)

    async def _db_resume_id(self, agent: Agent) -> str | None:
        if not self.db_enabled:
            return None
        try:
            return await get_session(
                job_id=self.job_id,
                agent_type=agent.spec.type.value,
            )
        except Exception:
            logger.exception("db get_session failed for agent %s", agent.agent_id)
            return None

    async def _fire(self, hook_name: str, payload: dict) -> None:
        """Fire a lifecycle hook; never raises."""
        await fire(hook_name, payload, hooks_dir=self.hooks_dir)

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Main job lifecycle: plan → execute → done."""
        await self._fire(PRE_JOB_START, pre_job_start_payload(self.job_id, self.description))
        try:
            await self._run_plan_phase()
            await self._run_execute_phase()
            self.phase = JobPhase.DONE
            self.status = JobStatus.DONE
        except Exception:
            self.status = JobStatus.FAILED
            await self._fire(
                POST_JOB_FAILED,
                post_job_done_payload(
                    job_id=self.job_id,
                    description=self.description,
                    status="failed",
                    total_cost_usd=self.cost_usd,
                    agents=self._agent_summaries(),
                ),
            )
            raise
        await self._fire(
            POST_JOB_DONE,
            post_job_done_payload(
                job_id=self.job_id,
                description=self.description,
                status="done",
                total_cost_usd=self.cost_usd,
                agents=self._agent_summaries(),
            ),
        )

    def _agent_summaries(self) -> list[dict]:
        return [
            {
                "type": a.spec.type.value,
                "status": a.status.value,
                "cost_usd": a.cost_usd,
                "session_id": a.session_id,
            }
            for a in self.agents
        ]

    async def _run_plan_phase(self) -> None:
        """Spawn the plan agent (Sonnet) and wait for job-plan.yaml."""
        self.phase = JobPhase.PLAN
        guard = self._make_guard()
        plan_agent = Agent(
            spec=AgentSpec(
                type=AgentType.PLAN,
                model=self.config.defaults.plan_model,
                cwd=str(self.workdir),
            ),
            job_id=self.job_id,
            agent_id=f"{self.job_id}-plan",
        )
        plan_agent.on_cost = self._make_on_cost(plan_agent, guard)
        if self.on_agent_ready:
            self.on_agent_ready(plan_agent)
        self.agents.append(plan_agent)

        resume_id = await self._db_resume_id(plan_agent)
        prompt = build_plan_prompt(
            description=self.description,
            plan_path=str(self.plan_path),
        )

        timeout = self.config.defaults.plan_timeout_s
        logger.info("job %s: starting plan phase (timeout=%ds)", self.job_id, timeout)

        try:
            await asyncio.wait_for(
                plan_agent.run(
                    prompt,
                    resume_session_id=resume_id,
                    system_prompt=PLAN_SYSTEM_PROMPT,
                ),
                timeout=timeout,
            )
        except (TimeoutError, asyncio.TimeoutError):
            plan_agent.status = AgentStatus.FAILED
            raise RuntimeError(f"Plan phase timed out after {timeout}s (job {self.job_id})")
        except CostLimitExceeded as exc:
            logger.warning("job %s: plan agent killed by cost guard: %s", self.job_id, exc)
            raise

        await self._db_upsert(plan_agent)
        await self._fire(
            POST_AGENT_DONE,
            post_agent_done_payload(
                job_id=self.job_id,
                agent_type=plan_agent.spec.type.value,
                status=plan_agent.status.value,
                session_id=plan_agent.session_id,
                cost_usd=plan_agent.cost_usd,
                description=self.description,
            ),
        )

        if not self.plan_path.exists():
            plan_agent.status = AgentStatus.FAILED
            raise RuntimeError(f"Plan agent finished but {self.plan_path} was not written")

        logger.info("job %s: plan phase complete (%s)", self.job_id, self.plan_path)

    def _make_guard(self) -> CostGuard:
        return CostGuard(
            max_per_agent=self.config.limits.max_cost_per_agent,
            max_per_job=self.config.limits.max_cost_per_job,
        )

    def _make_on_cost(self, agent: Agent, guard: CostGuard) -> Callable[[float], None]:
        """Return an on_cost callback that updates job total then enforces limits."""

        def on_cost(agent_cost: float) -> None:
            self.cost_usd = sum(a.cost_usd for a in self.agents)
            guard.check(agent_cost, self.cost_usd, agent.agent_id)

        return on_cost

    async def _run_execute_phase(self) -> None:
        """Parse plan, create worktrees, spawn execution agents respecting deps."""
        self.phase = JobPhase.EXECUTE
        if not self.plan_path.exists():
            return

        from claude_dispatch.plan import parse_plan, validate_plan

        job_plan = parse_plan(self.plan_path)
        validate_plan(job_plan, self.config)
        for wt in job_plan.worktrees:
            await self._create_worktree(wt.repo, wt.path, wt.branch)

        guard = self._make_guard()
        agents = []
        for spec in job_plan.agents:
            agent = Agent(
                spec=spec,
                job_id=self.job_id,
                agent_id=f"{self.job_id}-{spec.type.value}",
            )
            agent.on_cost = self._make_on_cost(agent, guard)
            if self.on_agent_ready:
                self.on_agent_ready(agent)
            agents.append(agent)
        for agent in agents:
            self.agents.append(agent)

        if agents:
            await self._schedule_agents(agents)

    async def _schedule_agents(self, agents: list[Agent]) -> None:
        """Run agents concurrently, honouring depends_on ordering."""
        by_type: dict[str, Agent] = {a.spec.type.value: a for a in agents}

        # Validate all declared deps exist in the plan
        for agent in agents:
            for dep in agent.spec.depends_on:
                if dep not in by_type:
                    raise ValueError(
                        f"Agent '{agent.spec.type.value}' depends on unknown type '{dep}'"
                    )

        # Detect cycles via DFS (WHITE=0, GRAY=1, BLACK=2)
        color: dict[str, int] = {t: 0 for t in by_type}

        def _dfs(node: str) -> None:
            color[node] = 1
            for dep in by_type[node].spec.depends_on:
                if color.get(dep, 0) == 1:
                    raise ValueError(f"Cycle in agent dependencies detected at '{dep}'")
                if color.get(dep, 0) == 0:
                    _dfs(dep)
            color[node] = 2

        for t in by_type:
            if color[t] == 0:
                _dfs(t)

        # One event per agent type — set when the agent finishes (success or fail)
        done_events: dict[str, asyncio.Event] = {t: asyncio.Event() for t in by_type}
        sem = asyncio.Semaphore(self.config.defaults.max_parallel_agents)

        async def run_agent(agent: Agent) -> None:
            # Wait for every dependency to finish before acquiring the semaphore
            for dep_type in agent.spec.depends_on:
                await done_events[dep_type].wait()

            resume_id = await self._db_resume_id(agent)
            prompt = build_execution_prompt(
                description=self.description,
                agent_type=agent.spec.type.value,
                plan_path=str(self.plan_path),
            )
            exc: Exception | None = None
            async with sem:
                try:
                    await agent.run(
                        prompt,
                        resume_session_id=resume_id,
                        system_prompt=EXECUTION_SYSTEM_PROMPT,
                    )
                except CostLimitExceeded as e:
                    logger.warning("agent %s killed by cost guard: %s", agent.agent_id, e)
                    exc = e
                except Exception as e:
                    logger.exception("agent %s failed", agent.agent_id)
                    exc = e
                finally:
                    # Persist session regardless of outcome, then notify and unblock
                    await self._db_upsert(agent)
                    await self._fire(
                        POST_AGENT_DONE,
                        post_agent_done_payload(
                            job_id=self.job_id,
                            agent_type=agent.spec.type.value,
                            status=agent.status.value,
                            session_id=agent.session_id,
                            cost_usd=agent.cost_usd,
                            description=self.description,
                        ),
                    )
                    done_events[agent.spec.type.value].set()
            if exc is not None:
                raise exc

        results = await asyncio.gather(*[run_agent(a) for a in agents], return_exceptions=True)

        failed = [agents[i].agent_id for i, r in enumerate(results) if isinstance(r, BaseException)]
        if failed:
            raise RuntimeError(f"Execute phase: agents failed: {', '.join(failed)}")

    async def _create_worktree(self, repo: str, path: str, branch: str) -> None:
        """Create a git worktree for the given repo."""
        repo_path = self.config.repos.get(repo)
        if not repo_path:
            raise ValueError(f"Repo '{repo}' not found in config.repos")
        proc = await asyncio.create_subprocess_exec(
            "git",
            "worktree",
            "add",
            "-b",
            branch,
            path,
            cwd=str(Path(repo_path).expanduser()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()

    def kill(self) -> None:
        """Kill all running agents and mark job as killed."""
        for agent in self.agents:
            if agent.status == AgentStatus.RUNNING:
                agent.status = AgentStatus.KILLED
        self.status = JobStatus.KILLED

    def _find_message_target(self, agent_type: str | None = None) -> Agent | None:
        """Return the best agent to receive an injected message.

        Priority:
        1. If *agent_type* is given, return that agent (or None if not found).
        2. Any RUNNING agent (first one found).
        3. Last DONE agent with a session_id (enables resume into a finished agent).
        """
        if agent_type is not None:
            return next((a for a in self.agents if a.spec.type.value == agent_type), None)
        running = next((a for a in self.agents if a.status == AgentStatus.RUNNING), None)
        if running:
            return running
        done_with_session = [
            a for a in self.agents if a.status == AgentStatus.DONE and a.session_id
        ]
        return done_with_session[-1] if done_with_session else None

    async def send_message(self, message: str, agent_type: str | None = None) -> bool:
        """Inject a user message into the job's coordination loop.

        If a matching agent is RUNNING, the message is queued in its inbox and
        delivered at the next SDK turn boundary.  If the agent is DONE (but has a
        session_id), a new SDK turn is started via ``agent.run()`` so the
        conversation is resumed.

        Returns True if a target was found and the message was delivered/queued.
        """
        target = self._find_message_target(agent_type)
        if target is None:
            logger.warning("send_message: no eligible agent in job %s", self.job_id)
            return False

        if target.status == AgentStatus.RUNNING:
            # Inbox — picked up at the next turn boundary inside Agent.run()
            target.send_message(message)
        else:
            # Resume a finished agent in a background task
            guard = self._make_guard()
            target.on_cost = self._make_on_cost(target, guard)
            asyncio.create_task(target.run(message, resume_session_id=target.session_id))
        return True
