"""Plan parser and validator — reads job-plan.yaml produced by the plan agent."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, Field

from claude_dispatch.agent import AgentSpec, AgentType

if TYPE_CHECKING:
    from claude_dispatch.config import Config

# Agent types that operate on files and therefore require a cwd.
_AGENTS_REQUIRING_CWD: frozenset[AgentType] = frozenset(
    {AgentType.CODE, AgentType.TEST, AgentType.REVIEW}
)


class PlanValidationError(ValueError):
    """Raised when job-plan.yaml fails validation.

    All errors are collected before raising so the caller gets the full picture
    in one shot (rather than fix-one-at-a-time iteration).
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        bullet_list = "\n  - ".join(errors)
        super().__init__(f"job-plan.yaml is invalid ({len(errors)} error(s)):\n  - {bullet_list}")


class WorktreeSpec(BaseModel):
    """A git worktree to create before spawning execution agents."""

    repo: str  # short name from config.repos
    path: str  # absolute path for the worktree
    branch: str  # branch to create in the worktree


class JobPlan(BaseModel):
    """Structured plan output from the plan agent."""

    agents: list[AgentSpec] = Field(default_factory=list)
    worktrees: list[WorktreeSpec] = Field(default_factory=list)
    summary: str = ""


def parse_plan(plan_path: Path) -> JobPlan:
    """Parse a job-plan.yaml file produced by the plan agent.

    Raises:
        FileNotFoundError: if the file does not exist.
        PlanValidationError: if the YAML is malformed or contains unknown agent types.
    """
    if not plan_path.exists():
        raise FileNotFoundError(f"Plan file not found: {plan_path}")

    with plan_path.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise PlanValidationError(["job-plan.yaml must be a YAML mapping, got a scalar/list"])

    parse_errors: list[str] = []
    agents: list[AgentSpec] = []

    for i, a in enumerate(raw.get("agents", [])):
        if not isinstance(a, dict):
            parse_errors.append(f"agents[{i}] must be a mapping, got {type(a).__name__}")
            continue
        raw_type = a.get("type", "")
        try:
            agent_type = AgentType(raw_type)
        except ValueError:
            valid = [t.value for t in AgentType]
            parse_errors.append(f"agents[{i}]: unknown type '{raw_type}' (valid: {valid})")
            continue
        agents.append(
            AgentSpec(
                type=agent_type,
                model=a.get("model"),
                cwd=a.get("cwd"),
                allowed_tools=a.get("allowed_tools", []),
                depends_on=a.get("depends_on", []),
            )
        )

    worktrees: list[WorktreeSpec] = []
    for j, w in enumerate(raw.get("resources", {}).get("worktrees", [])):
        if not isinstance(w, dict):
            parse_errors.append(f"resources.worktrees[{j}] must be a mapping")
            continue
        missing = [k for k in ("repo", "path", "branch") if not w.get(k)]
        if missing:
            parse_errors.append(f"resources.worktrees[{j}] missing required field(s): {missing}")
            continue
        worktrees.append(WorktreeSpec(**w))

    if parse_errors:
        raise PlanValidationError(parse_errors)

    return JobPlan(
        agents=agents,
        worktrees=worktrees,
        summary=raw.get("summary", ""),
    )


def validate_plan(plan: JobPlan, config: Config | None = None) -> None:
    """Validate a parsed JobPlan for logical consistency.

    Collects *all* errors before raising so callers see the full picture at once.

    Raises:
        PlanValidationError: if any check fails.
    """
    errors: list[str] = []
    by_type: dict[str, AgentSpec] = {}

    # 1. No duplicate agent types
    for spec in plan.agents:
        t = spec.type.value
        if t in by_type:
            errors.append(f"Duplicate agent type: '{t}'")
        else:
            by_type[t] = spec

    # 2. 'plan' must not appear as an execution agent
    if AgentType.PLAN.value in by_type:
        errors.append(
            "Agent type 'plan' must not appear in the execution agent list "
            "(the plan phase is handled automatically)"
        )

    # 3. cwd required for file-touching agents
    for spec in plan.agents:
        if spec.type in _AGENTS_REQUIRING_CWD and not spec.cwd:
            errors.append(f"Agent '{spec.type.value}' requires a 'cwd' field")

    # 4. depends_on targets must exist in the plan
    for spec in plan.agents:
        for dep in spec.depends_on:
            if dep not in by_type:
                errors.append(f"Agent '{spec.type.value}' depends_on unknown type '{dep}'")

    # 5. No dependency cycles (DFS — WHITE=0, GRAY=1, BLACK=2)
    color: dict[str, int] = {t: 0 for t in by_type}

    def _dfs(node: str) -> None:
        color[node] = 1
        for dep in by_type[node].depends_on:
            if dep not in by_type:
                continue  # already reported above
            if color.get(dep) == 1:
                errors.append(f"Cycle in depends_on: '{node}' → '{dep}'")
                return
            if color.get(dep) == 0:
                _dfs(dep)
        color[node] = 2

    for t in by_type:
        if color[t] == 0:
            _dfs(t)

    # 6. Worktree repos must be declared in config.repos
    if config and config.repos:
        known_repos = set(config.repos.keys())
        for wt in plan.worktrees:
            if wt.repo not in known_repos:
                errors.append(
                    f"Worktree repo '{wt.repo}' not in config.repos (known: {sorted(known_repos)})"
                )

    if errors:
        raise PlanValidationError(errors)
