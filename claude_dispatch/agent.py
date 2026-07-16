"""Agent — a single scoped Claude Code session managed by the SDK."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from claude_code_sdk import ClaudeCodeOptions, query
from claude_code_sdk.types import (
    AssistantMessage,
    HookContext,
    HookMatcher,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

logger = logging.getLogger(__name__)


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
    AgentType.PLAN: ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "Write"],
    AgentType.CODE: ["Bash", "Read", "Edit", "Write", "Glob", "Grep"],
    AgentType.JIRA: [],  # MCP tools only — added at runtime from config
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

    # Optional callbacks for live TUI updates
    on_log: Callable[[str], None] | None = field(default=None, repr=False)
    on_cost: Callable[[float], None] | None = field(default=None, repr=False)
    on_status: Callable[[AgentStatus], None] | None = field(default=None, repr=False)

    @property
    def model(self) -> str:
        return self.spec.model or AGENT_DEFAULT_MODELS[self.spec.type]

    @property
    def effective_tools(self) -> list[str]:
        """Spec-level overrides take precedence; fall back to type defaults."""
        return self.spec.allowed_tools or AGENT_DEFAULT_TOOLS[self.spec.type]

    def _set_status(self, status: AgentStatus) -> None:
        self.status = status
        if self.on_status:
            self.on_status(status)

    def _append_log(self, line: str) -> None:
        self.log_lines.append(line)
        if self.on_log:
            self.on_log(line)

    async def run(
        self,
        prompt: str,
        resume_session_id: str | None = None,
        system_prompt: str | None = None,
    ) -> str | None:
        """Run the agent with the given prompt via the Claude Code SDK.

        Returns the session_id on success (useful for resume), or None on failure.
        """
        self._set_status(AgentStatus.RUNNING)

        async def _track_cost(
            input_data: dict[str, Any],
            tool_use_id: str | None,
            context: HookContext,
        ) -> dict[str, Any]:
            """PostToolUse hook: accumulate cost from token usage."""
            usage = input_data.get("response", {}).get("usage", {})
            input_tokens: int = usage.get("input_tokens", 0)
            output_tokens: int = usage.get("output_tokens", 0)
            cost_delta = (input_tokens * 0.000003) + (output_tokens * 0.000015)
            self.cost_usd += cost_delta
            if self.on_cost:
                self.on_cost(self.cost_usd)
            return {}

        options = ClaudeCodeOptions(
            model=self.model,
            cwd=self.spec.cwd,
            permission_mode="bypassPermissions",
            allowed_tools=self.effective_tools,
            resume=resume_session_id,
            system_prompt=system_prompt,
            hooks={"PostToolUse": [HookMatcher(hooks=[_track_cost])]},
        )

        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            self._append_log(block.text)
                        elif isinstance(block, ToolUseBlock):
                            self.last_action = f"{block.name}(...)"
                            self._append_log(f"[tool] {block.name}")
                elif isinstance(message, ResultMessage):
                    self.session_id = message.session_id
                    if message.total_cost_usd is not None:
                        self.cost_usd = message.total_cost_usd
                        if self.on_cost:
                            self.on_cost(self.cost_usd)
                    final_status = AgentStatus.FAILED if message.is_error else AgentStatus.DONE
                    self._set_status(final_status)
                    logger.info(
                        "agent %s finished: status=%s cost=%.4f session=%s",
                        self.agent_id,
                        final_status,
                        self.cost_usd,
                        self.session_id,
                    )
        except Exception as exc:
            self._append_log(f"[error] {exc}")
            self._set_status(AgentStatus.FAILED)
            logger.exception("agent %s raised: %s", self.agent_id, exc)
            raise

        return self.session_id
