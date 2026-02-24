"""SQLite connection management for Medina."""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from medina.db.schema import INDEXES, TABLES

logger = logging.getLogger(__name__)

_DB_PATH: Path | None = None
_local = threading.local()


def _get_db_path() -> Path:
    """Return the configured DB path, falling back to default."""
    global _DB_PATH
    if _DB_PATH is not None:
        return _DB_PATH
    # Default location
    return Path(__file__).resolve().parents[3] / "output" / "medina.db"


def _run_auth_migrations(conn: sqlite3.Connection) -> None:
    """Add tenant_id column to projects if missing, and seed default tenant."""
    cursor = conn.execute("PRAGMA table_info(projects)")
    columns = {row[1] for row in cursor.fetchall()}
    if "tenant_id" not in columns:
        conn.execute("ALTER TABLE projects ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")
        logger.info("Added tenant_id column to projects table")

    # Ensure the default tenant exists (for backward compat with pre-auth data)
    conn.execute(
        "INSERT OR IGNORE INTO tenants (id, name) VALUES ('default', 'Default')"
    )
    conn.commit()


def init_db(db_path: str | Path | None = None) -> None:
    """Initialize the SQLite database.

    Creates the DB file, enables WAL mode, and creates all tables.
    Safe to call multiple times — tables use IF NOT EXISTS.
    """
    global _DB_PATH
    if db_path is not None:
        _DB_PATH = Path(db_path)
    path = _get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        for ddl in TABLES:
            conn.execute(ddl)
        # Run column migrations before indexes (indexes may reference new columns)
        _run_auth_migrations(conn)
        for idx in INDEXES:
            conn.execute(idx)
        conn.commit()
        logger.info("Database initialized at %s", path)
    finally:
        conn.close()


def get_conn() -> sqlite3.Connection:
    """Get a thread-local SQLite connection.

    Each thread gets its own connection (SQLite is not thread-safe by
    default).  Connections are reused within the same thread.
    """
    if not hasattr(_local, "conn") or _local.conn is None:
        path = _get_db_path()
        _local.conn = sqlite3.connect(str(path))
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


def close_db() -> None:
    """Close the thread-local connection (if any)."""
    if hasattr(_local, "conn") and _local.conn is not None:
        _local.conn.close()
        _local.conn = None
        logger.info("Database connection closed")
