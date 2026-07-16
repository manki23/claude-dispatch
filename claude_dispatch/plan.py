"""Plan parser — reads job-plan.yaml produced by the plan agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from claude_dispatch.agent import AgentSpec, AgentType


class WorktreeSpec(BaseModel):
    """A git worktree to create before spawning execution agents."""

    repo: str         # short name from config.repos
    path: str         # absolute path for the worktree
    branch: str       # branch to create in the worktree


class JobPlan(BaseModel):
    """Structured plan output from the plan agent."""

    agents: list[AgentSpec] = Field(default_factory=list)
    worktrees: list[WorktreeSpec] = Field(default_factory=list)
    summary: str = ""


def parse_plan(plan_path: Path) -> JobPlan:
    """Parse a job-plan.yaml file produced by the plan agent."""
    if not plan_path.exists():
        raise FileNotFoundError(f"Plan file not found: {plan_path}")

    with plan_path.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    agents = []
    for a in raw.get("agents", []):
        agents.append(
            AgentSpec(
                type=AgentType(a["type"]),
                model=a.get("model"),
                cwd=a.get("cwd"),
                allowed_tools=a.get("allowed_tools", []),
                depends_on=a.get("depends_on", []),
            )
        )

    worktrees = []
    for w in raw.get("resources", {}).get("worktrees", []):
        worktrees.append(WorktreeSpec(**w))

    return JobPlan(
        agents=agents,
        worktrees=worktrees,
        summary=raw.get("summary", ""),
    )
