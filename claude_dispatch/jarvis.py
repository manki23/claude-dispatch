"""Jarvis vault context lookup — injects prior work into plan prompts."""

from __future__ import annotations

import re
from pathlib import Path

_TICKET_RE = re.compile(r"\b([A-Z]+-\d+)\b")
_MAX_NOTE_CHARS = 2000


def fetch_prior_context(description: str, vault_path: Path) -> str | None:
    """Return a structured prior-context block from the Jarvis vault, or None.

    Algorithm:
    1. Extract Jira-style ticket IDs (e.g. ``MOPU-668``) from *description*.
    2. For each ID, glob the vault for a matching ``*.md`` note.
    3. Return a ``## Prior context`` block for injection into the plan prompt,
       or ``None`` if the vault is unavailable or no matches are found.

    The returned block is safe to prepend to any plan prompt — it includes
    an explicit instruction not to redo already-completed work.
    """
    if not vault_path.exists():
        return None

    tickets = list(dict.fromkeys(_TICKET_RE.findall(description)))  # dedupe, keep order
    if not tickets:
        return None

    sections: list[str] = []
    for ticket_id in tickets:
        matches = sorted(vault_path.glob(f"**/{ticket_id}*.md"))
        if not matches:
            continue
        note_path = matches[0]
        try:
            content = note_path.read_text(errors="replace").strip()
        except OSError:
            continue
        if len(content) > _MAX_NOTE_CHARS:
            content = content[:_MAX_NOTE_CHARS] + "\n… (truncated)"
        sections.append(f"### {ticket_id} — {note_path.name}\n{content}")

    if not sections:
        return None

    body = "\n\n".join(sections)
    return (
        "## Prior context (from Jarvis vault)\n\n"
        f"{body}\n\n"
        "Do NOT redo work already described above unless explicitly asked.\n"
    )
