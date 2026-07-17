"""Agent worker process — spawned per agent, survives TUI close.

Run as:
    python -m claude_dispatch.worker \\
        --job-id JID --agent-type code --agent-id JID-code \\
        --description "short name" --instructions "full task..." \\
        --prompt "Your task is..." --system-prompt "..." \\
        --cwd /path --model claude-haiku-4-5-20251001 \\
        --resume-session-id abc123 \\
        --log-path ~/.claude-dispatch/jobs/JID/code.log \\
        --db-path ~/.claude-dispatch/sessions.db

The worker updates the DB (status/session_id/cost) and appends every log
line to the log file.  Between SDK turns it drains the DB messages table so
the TUI can inject follow-up messages even while the agent is running.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


async def _run(args: argparse.Namespace) -> None:
    from claude_dispatch.agent import Agent, AgentSpec, AgentType
    from claude_dispatch.db import (
        DB_FILE,
        dequeue_messages,
        init_db,
        upsert_session,
        upsert_worker_meta,
    )

    db_path = Path(args.db_path) if args.db_path else DB_FILE
    log_path = Path(args.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    await init_db(db_path)

    # Register PID + log path so TUI can track us
    await upsert_worker_meta(
        job_id=args.job_id,
        agent_type=args.agent_type,
        pid=os.getpid(),
        log_path=str(log_path),
        db_path=db_path,
    )

    spec = AgentSpec(
        type=AgentType(args.agent_type),
        cwd=args.cwd or None,
        model=args.model or None,
        mcp_config_path=args.mcp_config_path or None,
    )
    agent = Agent(
        spec=spec,
        job_id=args.job_id,
        agent_id=args.agent_id,
        session_id=args.resume_session_id or None,
        log_path=str(log_path),
    )

    log_fh = log_path.open("a", buffering=1)
    agent.on_log = lambda line: print(line, file=log_fh, flush=True)

    # Mark running before first turn
    await upsert_session(
        job_id=args.job_id,
        agent_type=args.agent_type,
        session_id=args.resume_session_id or "",
        description=args.description,
        instructions=args.instructions,
        status="running",
        db_path=db_path,
    )

    status = "failed"
    try:
        current_prompt = args.prompt
        current_resume = args.resume_session_id or None

        while True:
            # Single SDK turn

            sys_prompt = args.system_prompt or None
            await agent._run_turn(current_prompt, current_resume, sys_prompt)
            current_resume = agent.session_id

            # Persist session_id after every turn so TUI can show it
            await upsert_session(
                job_id=args.job_id,
                agent_type=args.agent_type,
                session_id=agent.session_id or "",
                description=args.description,
                instructions=args.instructions,
                status="running",
                cost_usd=agent.cost_usd,
                db_path=db_path,
            )

            # Drain queued messages from TUI (written via enqueue_message)
            msgs = await dequeue_messages(args.job_id, args.agent_type, db_path=db_path)
            if msgs:
                current_prompt = msgs[0]
                print(f"[user] {current_prompt}", file=log_fh, flush=True)
                continue

            break

        status = "done"
    except Exception as e:
        print(f"[error] {e}", file=log_fh, flush=True)
        status = "failed"
    finally:
        await upsert_session(
            job_id=args.job_id,
            agent_type=args.agent_type,
            session_id=agent.session_id or "",
            description=args.description,
            instructions=args.instructions,
            status=status,
            cost_usd=agent.cost_usd,
            db_path=db_path,
        )
        log_fh.close()

    if status == "failed":
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Dispatch agent worker")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--agent-type", required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--instructions", default="")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--system-prompt", default="")
    parser.add_argument("--cwd", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--resume-session-id", default=None)
    parser.add_argument("--mcp-config-path", default=None)
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
