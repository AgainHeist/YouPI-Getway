"""SQLite persistence (prototype-grade, WAL, zero external services)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import settings

_local = threading.local()
_schema_ready = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    stages_done TEXT NOT NULL DEFAULT '[]',
    source_name TEXT,
    source_ext TEXT,
    source_bytes INTEGER,
    source_lang TEXT,
    target_lang TEXT,
    media TEXT,
    options TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    warning TEXT,
    input_mode TEXT NOT NULL DEFAULT 'auto',
    speakers TEXT NOT NULL DEFAULT '[]',
    artifacts TEXT NOT NULL DEFAULT '{}',
    verification TEXT NOT NULL DEFAULT '{}',
    notes TEXT NOT NULL DEFAULT '[]',
    client_ip TEXT,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);

CREATE TABLE IF NOT EXISTS segments (
    job_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    start_sec REAL NOT NULL,
    end_sec REAL NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    translated_text TEXT NOT NULL DEFAULT '',
    speaker TEXT NOT NULL DEFAULT 'SPEAKER_01',
    confidence REAL,
    tts_duration REAL,
    tempo REAL,
    flags TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (job_id, idx)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    ts REAL NOT NULL,
    stage TEXT NOT NULL,
    message TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    progress REAL
);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, id);

CREATE TABLE IF NOT EXISTS voice_previews (
    key TEXT PRIMARY KEY,
    job_id TEXT,
    lang TEXT NOT NULL,
    voice TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


def _connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or settings.db_path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_conn() -> sqlite3.Connection:
    global _schema_ready
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    if not _schema_ready:
        conn.executescript(SCHEMA)
        _schema_ready = True
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = get_conn()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_db(path: Path | None = None) -> None:
    global _schema_ready
    conn = _connect(path)
    try:
        conn.executescript(SCHEMA)
        _schema_ready = True
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def json_load(value, default):
    if value in (None, "", b""):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def json_dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def now() -> float:
    return time.time()
