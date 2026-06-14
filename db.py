"""db.py — SQLite data layer for alpha_kb.db.

All tables and indexes are created on first call to init_db().
Every other module (sync, validate, grade) depends on this layer.
"""

import sqlite3
from pathlib import Path
from typing import Optional
from datetime import datetime

DB_PATH = "alpha_kb.db"

# Locked schema — copied verbatim from 01-CONTEXT.md Specific Artifacts
_DDL = [
    """CREATE TABLE IF NOT EXISTS alphas (
  alpha_id TEXT PRIMARY KEY, expression TEXT NOT NULL, parent_alpha_id TEXT,
  archetype TEXT, region TEXT, universe TEXT, delay INTEGER,
  decay INTEGER, neutralization TEXT, truncation REAL, settings_json TEXT,
  sharpe REAL, fitness REAL, turnover REAL, returns REAL, drawdown REAL, margin REAL,
  long_count INTEGER, short_count INTEGER,
  self_corr REAL, prod_corr REAL, corr_checked_at TEXT, pnl_path TEXT,
  diagnosis TEXT,
  status TEXT, run_id TEXT, created_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS checks (
  alpha_id TEXT, name TEXT, result TEXT, value REAL, limit_val REAL, checked_at TEXT,
  PRIMARY KEY (alpha_id, name)
)""",
    """CREATE TABLE IF NOT EXISTS operators (
  name TEXT PRIMARY KEY, category TEXT, definition TEXT, signature TEXT
)""",
    """CREATE TABLE IF NOT EXISTS datafields (
  id TEXT, description TEXT, dataset TEXT, region TEXT,
  universe TEXT, delay INTEGER, type TEXT,
  PRIMARY KEY (id, region, universe, delay, dataset)
)""",
    """CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, thesis TEXT, started_at TEXT,
  iterations INTEGER, num_pass INTEGER, notes TEXT
)""",
    "CREATE INDEX IF NOT EXISTS idx_alphas_expr ON alphas(expression)",
    "CREATE INDEX IF NOT EXISTS idx_alphas_arch ON alphas(archetype, status)",
    """CREATE TABLE IF NOT EXISTS checks_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    alpha_id    TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    result      TEXT,
    value       REAL,
    limit_val   REAL,
    checked_at  TEXT    NOT NULL,
    run_tag     TEXT
)""",
    "CREATE INDEX IF NOT EXISTS idx_checks_history_alpha ON checks_history(alpha_id, name, checked_at)",
]

# Column order for alphas INSERT OR REPLACE (matches schema definition order)
_ALPHA_COLS = [
    "alpha_id", "expression", "parent_alpha_id", "archetype",
    "region", "universe", "delay", "decay", "neutralization", "truncation",
    "settings_json", "sharpe", "fitness", "turnover", "returns", "drawdown",
    "margin", "long_count", "short_count", "self_corr", "prod_corr",
    "corr_checked_at", "pnl_path", "diagnosis", "note_path",
    "status", "run_id", "created_at",
]


def init_db(path: str = DB_PATH) -> sqlite3.Connection:
    """Create all tables/indexes if not exist; return open connection.

    Enables WAL journal mode for concurrent read safety.
    The connection is NOT closed inside this function — the caller owns it.
    """
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    # Concurrent workers (grade_many max_workers>1) each open their own
    # connection; busy_timeout makes a writer wait for the lock instead of
    # immediately raising "database is locked".
    conn.execute("PRAGMA busy_timeout=30000")
    for stmt in _DDL:
        conn.execute(stmt)
    conn.commit()
    # Phase 3 idempotent migration: add diagnosis TEXT column to existing databases.
    # SQLite raises OperationalError("duplicate column name") for ADD COLUMN if it
    # already exists — catch and ignore to make this re-entrant across schema versions.
    try:
        conn.execute("ALTER TABLE alphas ADD COLUMN diagnosis TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists — idempotent
    # Phase 4 idempotent migration: add note_path TEXT column to alphas table.
    try:
        conn.execute("ALTER TABLE alphas ADD COLUMN note_path TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists — idempotent
    return conn


def upsert_alpha(conn: sqlite3.Connection, alpha_dict: dict) -> None:
    """INSERT OR REPLACE into alphas table. alpha_dict keys match column names."""
    placeholders = ", ".join("?" for _ in _ALPHA_COLS)
    col_list = ", ".join(_ALPHA_COLS)
    values = tuple(alpha_dict.get(col) for col in _ALPHA_COLS)
    conn.execute(
        f"INSERT OR REPLACE INTO alphas ({col_list}) VALUES ({placeholders})",
        values,
    )
    conn.commit()


def upsert_checks(conn: sqlite3.Connection, alpha_id: str, checks_list: list) -> None:
    """Bulk INSERT OR REPLACE into checks table from is.checks array.

    checks_list items: {name, result, value (may be None), limit (may be None)}
    from BRAIN is.checks response.
    """
    now = datetime.utcnow().isoformat()
    rows = [
        (
            alpha_id,
            c["name"],
            c.get("result"),
            c.get("value"),
            c.get("limit"),   # maps to limit_val column
            now,
        )
        for c in checks_list
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO checks (alpha_id, name, result, value, limit_val, checked_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def append_checks_history(
    conn: sqlite3.Connection,
    alpha_id: str,
    checks_list: list,
    run_tag: str = "",
) -> None:
    """Append check rows to checks_history (never overwrites). Thread-safe via WAL.

    Uses plain INSERT (not INSERT OR REPLACE) so every call adds new rows,
    preserving the full time-series history needed by the decay monitor.
    """
    now = datetime.utcnow().isoformat()
    rows = [
        (alpha_id, c["name"], c.get("result"), c.get("value"), c.get("limit"),
         now, run_tag)
        for c in checks_list
    ]
    conn.executemany(
        "INSERT INTO checks_history "
        "(alpha_id, name, result, value, limit_val, checked_at, run_tag) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def upsert_operators(conn: sqlite3.Connection, rows: list) -> None:
    """Bulk INSERT OR REPLACE into operators table.

    Each row dict: {name, category, definition, signature}.
    """
    data = [
        (r["name"], r.get("category"), r.get("definition"), r.get("signature"))
        for r in rows
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO operators (name, category, definition, signature) "
        "VALUES (?, ?, ?, ?)",
        data,
    )
    conn.commit()


def upsert_datafields(conn: sqlite3.Connection, rows: list) -> None:
    """Bulk INSERT OR REPLACE into datafields table.

    Each row dict: {id, description, dataset, region, universe, delay, type}.
    """
    data = [
        (
            r["id"],
            r.get("description"),
            r.get("dataset"),
            r.get("region"),
            r.get("universe"),
            r.get("delay"),
            r.get("type"),
        )
        for r in rows
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO datafields (id, description, dataset, region, universe, delay, type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        data,
    )
    conn.commit()


def expr_exists(
    conn: sqlite3.Connection,
    expression: str,
    delay: Optional[int] = None,
) -> Optional[str]:
    """Return alpha_id if expression already in alphas table, else None.

    Uses idx_alphas_expr index for fast lookup.

    Parameters
    ----------
    conn:       Open sqlite3.Connection.
    expression: Alpha expression string to look up.
    delay:      When provided (int), also matches on alphas.delay — which
                holds BRAIN's ACTUAL returned delay (set by the 2026-06-11
                recording fix).  A delay=0 query will NOT match a delay=1
                row for the same expression.  When None (default), the
                original expression-only query is used, preserving full
                backward compatibility for all existing callers (editor.py,
                grade.py, find_alphas.py, hunt._is_passable).
    """
    if delay is None:
        row = conn.execute(
            "SELECT alpha_id FROM alphas WHERE expression=? LIMIT 1",
            (expression,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT alpha_id FROM alphas WHERE expression=? AND delay=? LIMIT 1",
            (expression, delay),
        ).fetchone()
    return row[0] if row else None
