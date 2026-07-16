"""Agent — a single scoped Claude Code session managed by the SDK."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum


class AgentType(str, Enum):
    PLAN = "plan"
    CODE = "code"
    JIRA = "jira"
    TEST = "test"
    SLACK = "slack"
    REVIEW = "review"


class AgentStatus(str, Enum):
    WAITING = "waiting"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    KILLED = "killed"


# Default allowed tools per agent type.
# Agents are locked to this list — they cannot use tools outside it.
AGENT_DEFAULT_TOOLS: dict[AgentType, list[str]] = {
    AgentType.PLAN: ["Read", "Glob", "Grep", "WebSearch", "WebFetch"],
    AgentType.CODE: ["Bash", "Read", "Edit", "Write", "Glob", "Grep"],
    AgentType.JIRA: [],   # MCP tools only — added at runtime from config
    AgentType.TEST: ["Bash"],
    AgentType.SLACK: [],  # MCP tools only
    AgentType.REVIEW: ["Read", "Glob", "Grep"],
}

# Default model per agent type.
AGENT_DEFAULT_MODELS: dict[AgentType, str] = {
    AgentType.PLAN: "claude-sonnet-4-6",
    AgentType.CODE: "claude-haiku-4-5-20251001",
    AgentType.JIRA: "claude-haiku-4-5-20251001",
    AgentType.TEST: "claude-haiku-4-5-20251001",
    AgentType.SLACK: "claude-haiku-4-5-20251001",
    AgentType.REVIEW: "claude-sonnet-4-6",
}


@dataclass
class AgentSpec:
    """Declaration of an agent inside a Job (from plan.yaml or defaults)."""

    type: AgentType
    model: str | None = None
    cwd: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)  # other agent type names


@dataclass
class Agent:
    """Runtime state of a running or completed agent."""

    spec: AgentSpec
    job_id: str
    agent_id: str
    status: AgentStatus = AgentStatus.WAITING
    session_id: str | None = None
    cost_usd: float = 0.0
    last_action: str = ""
    log_lines: list[str] = field(default_factory=list)

    @property
    def model(self) -> str:
        return self.spec.model or AGENT_DEFAULT_MODELS[self.spec.type]

    @property
    def effective_cwd(self) -> str | None:
        return self.spec.cwd

    async def stream_output(self) -> AsyncIterator[str]:
        """Placeholder: yield log lines as they arrive from the SDK."""
        # TODO: wire to Claude Agent SDK streaming output
        yield f"[{self.spec.type}] Starting..."
        await asyncio.sleep(0)
