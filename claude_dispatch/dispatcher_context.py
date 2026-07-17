"""Dispatcher context builder — generates the system prompt for the dispatcher agent."""

from __future__ import annotations

from claude_dispatch.agent import AgentStatus
from claude_dispatch.job import Job, JobStatus

_DISPATCHER_PREAMBLE = """\
You are the dispatcher for claude-dispatch, a tool that orchestrates parallel Claude Code sessions.

## What you can do
- Answer questions about job progress, agent status, costs, and blockers
- Summarise what agents have done (use the log snippets below)
- Explain why something might have failed

## What you CANNOT do — HARD RULES, no exceptions
- NEVER run shell commands, create files, modify git repos, push branches, create PRs, or take
  any action on the user's filesystem or GitHub
- NEVER execute code of any kind
- If the user asks you to perform an action (not just describe it), refuse and explain that
  they should route the instruction to the relevant job using the @ syntax below

## How to route instructions to a running job
You cannot route messages yourself. Tell the user to type this in the input:

    @<job_id>:<agent_type> <message>

Example: `@abc123:code change the remote origin to git@github.com:ddoghq/dogweb.git`

The job_id values are listed in the ## Current jobs section below.
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
            f"### [{status_icon}] job_id={job.job_id}  status={job.status.value}/{job.phase.value}"
            f"  cost=${job.cost_usd:.4f}"
        )
        lines.append(f"description: {job.description}")

        if job.agents:
            lines.append("agents:")
            for agent in job.agents:
                agent_status = agent.status
                last = f"  last_action={agent.last_action!r}" if agent.last_action else ""
                lines.append(
                    f"  - type={agent.spec.type.value}  status={agent_status.value}"
                    f"  ${agent.cost_usd:.4f}{last}"
                )
                # Last 5 log lines for running agents — gives real context
                if agent_status == AgentStatus.RUNNING and agent.log_lines:
                    for log_line in agent.log_lines[-5:]:
                        lines.append(f"    > {log_line}")
        lines.append("")

    return "\n".join(lines)
