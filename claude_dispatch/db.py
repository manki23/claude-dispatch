"""SQLite session index — maps (job_id, agent_type) to SDK session IDs for resume."""

from __future__ import annotations

import aiosqlite

from claude_dispatch.config import DB_FILE


CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    job_id      TEXT NOT NULL,
    agent_type  TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    description TEXT,
    status      TEXT,
    cost_usd    REAL DEFAULT 0.0,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (job_id, agent_type)
)
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(CREATE_TABLE)
        await db.commit()


async def upsert_session(
    job_id: str,
    agent_type: str,
    session_id: str,
    description: str = "",
    status: str = "running",
    cost_usd: float = 0.0,
) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """
            INSERT INTO sessions (job_id, agent_type, session_id, description, status, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, agent_type) DO UPDATE SET
                session_id = excluded.session_id,
                status = excluded.status,
                cost_usd = excluded.cost_usd,
                updated_at = datetime('now')
            """,
            (job_id, agent_type, session_id, description, status, cost_usd),
        )
        await db.commit()


async def get_session(job_id: str, agent_type: str) -> str | None:
    """Return the SDK session_id for a given job+agent, or None if not found."""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT session_id FROM sessions WHERE job_id = ? AND agent_type = ?",
            (job_id, agent_type),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def list_jobs() -> list[dict]:
    """Return all known jobs with their latest status and cost."""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            """
            SELECT job_id, description, status, SUM(cost_usd) as total_cost, MAX(updated_at)
            FROM sessions
            GROUP BY job_id
            ORDER BY MAX(updated_at) DESC
            """
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "job_id": r[0],
                    "description": r[1],
                    "status": r[2],
                    "cost_usd": r[3] or 0.0,
                    "updated_at": r[4],
                }
                for r in rows
            ]
