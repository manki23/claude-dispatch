"""SQLite session index — maps (job_id, agent_type) to SDK session IDs for resume."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from claude_dispatch.config import DB_FILE

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    job_id       TEXT NOT NULL,
    agent_type   TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    description  TEXT,
    instructions TEXT,
    status       TEXT,
    cost_usd     REAL DEFAULT 0.0,
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (job_id, agent_type)
)
"""


async def init_db(db_path: Path = DB_FILE) -> None:
    """Create the sessions table if it does not exist, migrating older DBs."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(CREATE_TABLE)
        # Migrate: add instructions column if missing (idempotent)
        try:
            await db.execute("ALTER TABLE sessions ADD COLUMN instructions TEXT")
        except Exception:
            pass  # column already exists
        await db.commit()


async def upsert_session(
    job_id: str,
    agent_type: str,
    session_id: str,
    description: str = "",
    instructions: str = "",
    status: str = "running",
    cost_usd: float = 0.0,
    db_path: Path = DB_FILE,
) -> None:
    """Insert or update a session row."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO sessions (job_id, agent_type, session_id, description, instructions, status, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, agent_type) DO UPDATE SET
                session_id   = excluded.session_id,
                status       = excluded.status,
                cost_usd     = excluded.cost_usd,
                updated_at   = datetime('now')
            """,
            (job_id, agent_type, session_id, description, instructions, status, cost_usd),
        )
        await db.commit()


async def get_session(
    job_id: str,
    agent_type: str,
    db_path: Path = DB_FILE,
) -> str | None:
    """Return the SDK session_id for a given job+agent, or None if not found."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT session_id FROM sessions WHERE job_id = ? AND agent_type = ?",
            (job_id, agent_type),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def list_jobs(db_path: Path = DB_FILE) -> list[dict]:
    """Return all known jobs with their latest status and aggregated cost."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT job_id, description, instructions, status, SUM(cost_usd) as total_cost, MAX(updated_at)
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
                    "instructions": r[2] or "",
                    "status": r[3],
                    "cost_usd": r[4] or 0.0,
                    "updated_at": r[5],
                }
                for r in rows
            ]


async def list_agents(job_id: str, db_path: Path = DB_FILE) -> list[dict]:
    """Return all agent rows for a specific job, ordered by creation time."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT agent_type, session_id, status, cost_usd, created_at, updated_at
            FROM sessions
            WHERE job_id = ?
            ORDER BY created_at ASC
            """,
            (job_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "agent_type": r[0],
                    "session_id": r[1],
                    "status": r[2],
                    "cost_usd": r[3] or 0.0,
                    "created_at": r[4],
                    "updated_at": r[5],
                }
                for r in rows
            ]


async def delete_job(job_id: str, db_path: Path = DB_FILE) -> None:
    """Remove all session rows for a job (used when a job is killed/discarded)."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM sessions WHERE job_id = ?", (job_id,))
        await db.commit()
