"""
db.py — SQLite storage layer for the network monitor.

Design:
  - `samples` stores raw deltas as they come in from the collector
    (one row per process per poll interval). This is the source of truth
    and lets us re-aggregate however we like later (today/week/month/etc).
  - We store a UNIX timestamp (UTC) plus a local calendar `day` string
    (YYYY-MM-DD) computed at insert time, so day/week/month rollups are
    just cheap SQL queries instead of re-parsing timestamps constantly.
  - Bytes are stored as integers (bytes), never floats, to avoid drift
    from repeated unit conversions.
"""

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path.home() / ".local" / "share" / "netmonitor" / "netmonitor.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,      -- unix timestamp (UTC) when sample was recorded
    day         TEXT    NOT NULL,      -- local YYYY-MM-DD, for fast day/week/month grouping
    process     TEXT    NOT NULL,      -- process name as reported by nethogs
    interface   TEXT,                  -- network interface, if known
    down_bytes  INTEGER NOT NULL DEFAULT 0,  -- bytes received in this interval
    up_bytes    INTEGER NOT NULL DEFAULT 0   -- bytes sent in this interval
);

CREATE INDEX IF NOT EXISTS idx_samples_day ON samples(day);
CREATE INDEX IF NOT EXISTS idx_samples_process ON samples(process);
CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts);

-- Bookkeeping table so `reset` can wipe stats without losing the fact
-- that monitoring has been running since some earlier date.
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")  # safe for a writer + reader running concurrently
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def connect():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def insert_sample(conn, process: str, interface: str, down_bytes: int, up_bytes: int, ts: float | None = None):
    """Insert one raw sample. Called by the collector every poll interval."""
    ts = ts if ts is not None else time.time()
    day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO samples (ts, day, process, interface, down_bytes, up_bytes) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (int(ts), day, process, interface, int(down_bytes), int(up_bytes)),
    )


def set_meta(conn, key: str, value: str):
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_meta(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def totals_since(conn, since_ts: float | None, process: str | None = None):
    """
    Aggregate download/upload totals, optionally filtered by a start timestamp
    and/or a single process. since_ts=None means all-time (lifetime).
    """
    where = []
    params = []
    if since_ts is not None:
        where.append("ts >= ?")
        params.append(int(since_ts))
    if process is not None:
        where.append("process = ?")
        params.append(process)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    row = conn.execute(
        f"SELECT COALESCE(SUM(down_bytes),0), COALESCE(SUM(up_bytes),0) FROM samples {clause}",
        params,
    ).fetchone()
    return {"down": row[0], "up": row[1]}


def per_app_since(conn, since_ts: float | None, limit: int = 50):
    """Per-process totals since a given timestamp, sorted by total desc."""
    where = "WHERE ts >= ?" if since_ts is not None else ""
    params = [int(since_ts)] if since_ts is not None else []
    rows = conn.execute(
        f"""
        SELECT process,
               COALESCE(SUM(down_bytes),0) AS down,
               COALESCE(SUM(up_bytes),0) AS up,
               COALESCE(SUM(down_bytes+up_bytes),0) AS total
        FROM samples
        {where}
        GROUP BY process
        ORDER BY total DESC
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    return [{"process": r[0], "down": r[1], "up": r[2], "total": r[3]} for r in rows]


def all_rows_for_export(conn, since_ts: float | None = None):
    where = "WHERE ts >= ?" if since_ts is not None else ""
    params = [int(since_ts)] if since_ts is not None else []
    return conn.execute(
        f"SELECT ts, day, process, interface, down_bytes, up_bytes FROM samples {where} ORDER BY ts",
        params,
    ).fetchall()


def reset_stats(conn):
    conn.execute("DELETE FROM samples")
    set_meta(conn, "reset_at", str(int(time.time())))
