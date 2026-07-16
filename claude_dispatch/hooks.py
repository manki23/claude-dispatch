"""Lifecycle hooks — fire executable scripts in ~/.claude-dispatch/hooks/."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from claude_dispatch.config import load_config

logger = logging.getLogger(__name__)

# ── event name constants ──────────────────────────────────────────────────────

PRE_JOB_START = "pre_job_start"
POST_AGENT_DONE = "post_agent_done"
POST_JOB_DONE = "post_job_done"
POST_JOB_FAILED = "post_job_failed"

# ── payload builders ──────────────────────────────────────────────────────────


def pre_job_start_payload(job_id: str, description: str) -> dict[str, Any]:
    return {"event": PRE_JOB_START, "job_id": job_id, "description": description}


def post_agent_done_payload(
    job_id: str,
    agent_type: str,
    status: str,
    session_id: str | None,
    cost_usd: float,
    description: str,
) -> dict[str, Any]:
    return {
        "event": POST_AGENT_DONE,
        "job_id": job_id,
        "agent_type": agent_type,
        "status": status,
        "session_id": session_id,
        "cost_usd": cost_usd,
        "description": description,
    }


def post_job_done_payload(
    job_id: str,
    description: str,
    status: str,
    total_cost_usd: float,
    agents: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "event": POST_JOB_DONE if status == "done" else POST_JOB_FAILED,
        "job_id": job_id,
        "description": description,
        "status": status,
        "total_cost_usd": total_cost_usd,
        "agents": agents,
    }


# ── fire ─────────────────────────────────────────────────────────────────────


async def fire(
    hook_name: str,
    payload: dict[str, Any],
    *,
    hooks_dir: Path | None = None,
    enabled: bool | None = None,
) -> None:
    """Fire a lifecycle hook if it exists and is executable.

    Hook scripts receive a JSON payload on stdin.
    Errors are logged but never propagate — hooks are best-effort.

    Args:
        hook_name: Filename of the hook script (e.g. ``"post_job_done"``).
        payload:   JSON-serialisable dict passed to the script via stdin.
        hooks_dir: Override the hooks directory (useful in tests).
        enabled:   Override the config ``hooks.enabled`` flag (useful in tests).
    """
    if enabled is None or hooks_dir is None:
        config = load_config()
        if enabled is None:
            enabled = config.hooks.enabled
        if hooks_dir is None:
            hooks_dir = Path(config.hooks.directory).expanduser()

    if not enabled:
        return

    hook_path = hooks_dir / hook_name
    if not hook_path.exists() or not hook_path.is_file():
        return
    if not hook_path.stat().st_mode & 0o111:
        logger.warning("Hook %s exists but is not executable — skipping", hook_name)
        return

    payload_json = json.dumps(payload).encode()
    try:
        proc = await asyncio.create_subprocess_exec(
            str(hook_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(
            proc.communicate(input=payload_json),
            timeout=30.0,
        )
        if proc.returncode != 0:
            logger.warning(
                "Hook %s exited with code %d: %s",
                hook_name,
                proc.returncode,
                stderr.decode().strip(),
            )
    except (asyncio.TimeoutError, TimeoutError):
        logger.warning("Hook %s timed out after 30s", hook_name)
    except Exception as exc:
        logger.warning("Hook %s failed: %s", hook_name, exc)
