"""Lifecycle hooks — fire executable scripts in ~/.claude-dispatch/hooks/."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from claude_dispatch.config import load_config

logger = logging.getLogger(__name__)


async def fire(hook_name: str, payload: dict[str, Any]) -> None:
    """
    Fire a lifecycle hook if it exists and is executable.

    Hook scripts receive a JSON payload via stdin.
    Errors are logged but never propagate — hooks are best-effort.
    """
    config = load_config()
    if not config.hooks.enabled:
        return

    hook_path = Path(config.hooks.directory).expanduser() / hook_name
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
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=payload_json),
            timeout=30.0,
        )
        if proc.returncode != 0:
            logger.warning(
                "Hook %s exited with code %d: %s",
                hook_name, proc.returncode, stderr.decode().strip(),
            )
    except asyncio.TimeoutError:
        logger.warning("Hook %s timed out after 30s", hook_name)
    except Exception as e:
        logger.warning("Hook %s failed: %s", hook_name, e)
