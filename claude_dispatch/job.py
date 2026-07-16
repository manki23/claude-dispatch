"""Job — lifecycle manager for a single human task."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from claude_dispatch.agent import Agent, AgentSpec, AgentStatus, AgentType
from claude_dispatch.config import Config


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

    async def run(self) -> None:
        """Main job lifecycle: plan → execute → done."""
        try:
            await self._run_plan_phase()
            await self._run_execute_phase()
            self.phase = JobPhase.DONE
            self.status = JobStatus.DONE
        except Exception:
            self.status = JobStatus.FAILED
            raise

    async def _run_plan_phase(self) -> None:
        """Spawn the plan agent (Sonnet) and wait for job-plan.yaml."""
        self.phase = JobPhase.PLAN
        plan_agent = Agent(
            spec=AgentSpec(type=AgentType.PLAN, cwd=str(self.workdir)),
            job_id=self.job_id,
            agent_id=f"{self.job_id}-plan",
        )
        self.agents.append(plan_agent)
        # TODO: run via Claude Agent SDK, wait for plan_path to appear
        plan_agent.status = AgentStatus.RUNNING
        await asyncio.sleep(0)

    async def _run_execute_phase(self) -> None:
        """Parse plan, create worktrees, spawn execution agents respecting deps."""
        self.phase = JobPhase.EXECUTE
        if not self.plan_path.exists():
            return

        from claude_dispatch.plan import parse_plan

        job_plan = parse_plan(self.plan_path)
        for wt in job_plan.worktrees:
            await self._create_worktree(wt.repo, wt.path, wt.branch)

        # TODO: implement dependency-aware scheduling (issue #3)
        for spec in job_plan.agents:
            agent = Agent(
                spec=spec,
                job_id=self.job_id,
                agent_id=f"{self.job_id}-{spec.type.value}",
            )
            self.agents.append(agent)

    async def _create_worktree(self, repo: str, path: str, branch: str) -> None:
        """Create a git worktree for the given repo."""
        repo_path = self.config.repos.get(repo)
        if not repo_path:
            raise ValueError(f"Repo '{repo}' not found in config.repos")
        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "add", "-b", branch, path,
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

    def send_message(self, message: str) -> None:
        """Inject a user message into the job's coordination loop."""
        # TODO: route to active agent via SDK stdin injection (issue #1)
        pass
