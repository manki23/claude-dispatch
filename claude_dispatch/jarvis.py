"""Jarvis vault context lookup — injects prior work into plan prompts."""

from __future__ import annotations

import re
from pathlib import Path

_TICKET_RE = re.compile(r"\b([A-Z]+-\d+)\b")
# Matches ticket ID followed by a non-digit — prevents MOPU-668 matching MOPU-6680.
_TICKET_STEM_RE = re.compile(r"^([A-Z]+-\d+)[^0-9]")
_MAX_NOTE_CHARS = 2000


def _build_vault_index(vault_path: Path) -> dict[str, Path]:
    """Walk the vault once and return a dict mapping ticket ID -> first matching note path.

    A note matches ticket T when its stem starts with T followed by a
    non-digit character (space, dash, underscore ...), so MOPU-668 - title.md
    matches MOPU-668 but not MOPU-6680.
    """
    index: dict[str, Path] = {}
    for note in sorted(vault_path.rglob("*.md")):
        m = _TICKET_STEM_RE.match(note.stem)
        if m:
            ticket_id = m.group(1)
            index.setdefault(ticket_id, note)
    return index


def fetch_prior_context(description: str, vault_path: Path) -> str | None:
    """Return a structured prior-context block from the Jarvis vault, or None.

    Algorithm:
    1. Extract Jira-style ticket IDs (e.g. MOPU-668) from description.
    2. Walk the vault once (single rglob) and build a ticket->note index.
    3. Return a ## Prior context block for injection into the plan prompt,
       or None if the vault is unavailable or no matches are found.

    The returned block is safe to prepend to any plan prompt -- it includes
    an explicit instruction not to redo already-completed work.
    """
    if not vault_path.exists():
        return None

    tickets = list(dict.fromkeys(_TICKET_RE.findall(description)))  # dedupe, keep order
    if not tickets:
        return None

    index = _build_vault_index(vault_path)

    sections: list[str] = []
    for ticket_id in tickets:
        note_path = index.get(ticket_id)
        if note_path is None:
            continue
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
