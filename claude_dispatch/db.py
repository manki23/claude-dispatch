"""SQLite session index — maps (job_id, agent_type) to SDK session IDs for resume.

Also stores worker PIDs, log file paths, and a messages queue for TUI→agent IPC.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from claude_dispatch.config import DB_FILE

CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    job_id       TEXT NOT NULL,
    agent_type   TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    description  TEXT,
    instructions TEXT,
    status       TEXT,
    cost_usd     REAL DEFAULT 0.0,
    pid          INTEGER,
    log_path     TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (job_id, agent_type)
)
"""

CREATE_MESSAGES = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL,
    agent_type  TEXT NOT NULL,
    text        TEXT NOT NULL,
    consumed    INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
)
"""

_MIGRATIONS = [
    "ALTER TABLE sessions ADD COLUMN instructions TEXT",
    "ALTER TABLE sessions ADD COLUMN pid INTEGER",
    "ALTER TABLE sessions ADD COLUMN log_path TEXT",
]


async def init_db(db_path: Path = DB_FILE) -> None:
    """Create tables if they do not exist; run idempotent column migrations."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(CREATE_SESSIONS)
        await db.execute(CREATE_MESSAGES)
        for stmt in _MIGRATIONS:
            try:
                await db.execute(stmt)
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
    """Insert or update a session row (does not touch pid/log_path)."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO sessions
                (job_id, agent_type, session_id, description, instructions, status, cost_usd)
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


async def upsert_worker_meta(
    job_id: str,
    agent_type: str,
    pid: int,
    log_path: str,
    db_path: Path = DB_FILE,
) -> None:
    """Store the PID and log path for a running worker subprocess."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE sessions SET pid = ?, log_path = ?, updated_at = datetime('now')
            WHERE job_id = ? AND agent_type = ?
            """,
            (pid, log_path, job_id, agent_type),
        )
        if db.total_changes == 0:
            # Row doesn't exist yet — insert minimal placeholder
            await db.execute(
                """
                INSERT OR IGNORE INTO sessions
                    (job_id, agent_type, session_id, status, pid, log_path)
                VALUES (?, ?, '', 'running', ?, ?)
                """,
                (job_id, agent_type, pid, log_path),
            )
        await db.commit()


async def enqueue_message(
    job_id: str,
    agent_type: str,
    text: str,
    db_path: Path = DB_FILE,
) -> None:
    """Queue a user message for delivery to a running worker at the next turn boundary."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO messages (job_id, agent_type, text) VALUES (?, ?, ?)",
            (job_id, agent_type, text),
        )
        await db.commit()


async def dequeue_messages(
    job_id: str,
    agent_type: str,
    db_path: Path = DB_FILE,
) -> list[str]:
    """Return and mark-consumed all pending messages for this agent."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT id, text FROM messages"
            " WHERE job_id=? AND agent_type=? AND consumed=0 ORDER BY id",
            (job_id, agent_type),
        ) as cursor:
            rows = await cursor.fetchall()
        if rows:
            ids = [r[0] for r in rows]
            placeholders = ",".join("?" * len(ids))
            await db.execute(
                f"UPDATE messages SET consumed=1 WHERE id IN ({placeholders})", ids
            )
            await db.commit()
        return [r[1] for r in rows]


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
            SELECT job_id, description, instructions, status,
                   SUM(cost_usd) as total_cost, MAX(updated_at)
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
            SELECT agent_type, session_id, status, cost_usd, created_at, updated_at, pid, log_path
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
                    "pid": r[6],
                    "log_path": r[7],
                }
                for r in rows
            ]


async def delete_job(job_id: str, db_path: Path = DB_FILE) -> None:
    """Remove all session rows for a job (used when a job is killed/discarded)."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM sessions WHERE job_id = ?", (job_id,))
        await db.execute("DELETE FROM messages WHERE job_id = ?", (job_id,))
        await db.commit()
