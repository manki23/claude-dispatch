"""Dispatcher context builder — generates the system prompt for the dispatcher agent."""

from __future__ import annotations

from claude_dispatch.agent import AgentStatus
from claude_dispatch.job import Job, JobStatus


_DISPATCHER_PREAMBLE = """\
You are the dispatcher for claude-dispatch, a tool that orchestrates parallel Claude Code sessions.
You have read-only visibility into all running and completed jobs.
Answer questions about job progress, agent status, costs, and blockers.
Be concise and direct. Never invent information not present in the context below.
"""


def build_dispatcher_system_prompt(jobs: list[Job]) -> str:
    """Build a fresh system prompt from current job state.

    Called before each dispatcher turn so the agent always sees live data.
    """
    if not jobs:
        return _DISPATCHER_PREAMBLE + "\nNo jobs are currently loaded.\n"

    lines: list[str] = [_DISPATCHER_PREAMBLE, "## Current jobs\n"]
    for job in jobs:
        status_icon = {
            JobStatus.RUNNING: "●",
            JobStatus.DONE: "✓",
            JobStatus.FAILED: "✗",
            JobStatus.KILLED: "⊘",
        }.get(job.status, "?")

        lines.append(
            f"### [{status_icon}] {job.job_id}  {job.status.value}/{job.phase.value}"
            f"  cost=${job.cost_usd:.4f}"
        )
        lines.append(f"description: {job.description}")

        if job.agents:
            lines.append("agents:")
            for agent in job.agents:
                agent_status = agent.status
                last = f"  last={agent.last_action}" if agent.last_action else ""
                lines.append(
                    f"  - {agent.spec.type.value}  {agent_status.value}"
                    f"  ${agent.cost_usd:.4f}{last}"
                )
                # Include the last 3 log lines for running agents
                if agent_status == AgentStatus.RUNNING and agent.log_lines:
                    for log_line in agent.log_lines[-3:]:
                        lines.append(f"    > {log_line}")
        lines.append("")

    return "\n".join(lines)
