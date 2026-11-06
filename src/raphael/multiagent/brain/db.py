"""SQLite schema and connection management for the raphael-ma brain.

The connection is created with ``check_same_thread=False`` and every
statement/commit is serialized through an RLock: the teams orchestrator
runs team phases in a ThreadPoolExecutor, and SQLite connections are not
safe for unserialized cross-thread use. WAL + busy_timeout additionally
tolerate other *processes* (e.g. a second CLI invocation) touching the
same brain.db.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, FrozenSet, Optional

from raphael.multiagent.log import get_logger
from raphael.multiagent.paths import db_path

log = get_logger("brain")

# Tables the `brain reset` command is allowed to wipe. This is a fixed
# allowlist — user input never reaches table names. The identifier guard in
# BrainDB.wipe() makes the invariant explicit even if this ever gets refactored.
WIPEABLE_TABLES: FrozenSet[str] = frozenset(
    {"sessions", "turns", "insights", "outcomes", "evolutions"}
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id            TEXT PRIMARY KEY,
  kind          TEXT NOT NULL,          -- debate | community | teams
  topic         TEXT NOT NULL,
  mode          TEXT NOT NULL,          -- mock | live
  started_at    TEXT NOT NULL,
  finished_at   TEXT,
  verdict_json  TEXT,
  transcript_path TEXT,
  metrics_json  TEXT
);
CREATE TABLE IF NOT EXISTS turns (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id    TEXT NOT NULL REFERENCES sessions(id),
  seq           INTEGER NOT NULL,
  agent         TEXT NOT NULL,
  team          TEXT,
  role          TEXT,
  phase         TEXT,                   -- debate | community | team | integration
  round         INTEGER,
  provider      TEXT,
  model         TEXT,
  content       TEXT NOT NULL,
  latency_ms    REAL,
  ok            INTEGER DEFAULT 1,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
CREATE TABLE IF NOT EXISTS insights (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id      TEXT REFERENCES sessions(id),
  text            TEXT NOT NULL,
  confidence      REAL NOT NULL DEFAULT 0.5,
  weight          REAL NOT NULL DEFAULT 0.5,
  times_used      INTEGER NOT NULL DEFAULT 0,
  times_confirmed INTEGER NOT NULL DEFAULT 0,
  times_contradicted INTEGER NOT NULL DEFAULT 0,
  embedding       BLOB,
  active          INTEGER NOT NULL DEFAULT 1,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outcomes (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id    TEXT REFERENCES sessions(id),
  subject       TEXT NOT NULL,          -- agent name or team name
  subject_type  TEXT NOT NULL,          -- agent | team
  score         REAL NOT NULL,
  detail_json   TEXT,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outcomes_subject ON outcomes(subject);
CREATE TABLE IF NOT EXISTS evolutions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  kind          TEXT NOT NULL,          -- persona | strategy | routing
  edits_json    TEXT NOT NULL,
  reason        TEXT,
  status        TEXT NOT NULL,          -- candidate | active | kept | reverted
  metrics_before_json TEXT,
  metrics_after_json  TEXT,
  eval_after    INTEGER NOT NULL DEFAULT 5,   -- sessions before evaluation
  sessions_seen INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL,
  decided_at    TEXT
);
CREATE TABLE IF NOT EXISTS personas (
  role          TEXT NOT NULL,
  version       INTEGER NOT NULL,
  prompt        TEXT NOT NULL,
  active        INTEGER NOT NULL DEFAULT 0,
  note          TEXT,
  created_at    TEXT NOT NULL,
  PRIMARY KEY (role, version)
);
CREATE TABLE IF NOT EXISTS meta (
  key           TEXT PRIMARY KEY,
  value         TEXT
);
"""


class BrainDB:
    def __init__(self, path: Optional[Path] = None, home: Optional[Path] = None):
        if path is None:
            path = db_path(home) if home else db_path(Path(".raphael/ma"))
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # -- convenience ------------------------------------------------------
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, params)

    def query(self, sql: str, params: tuple = ()) -> list:
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, params).fetchone()

    def commit(self) -> None:
        with self._lock:
            self.conn.commit()

    def rollback(self) -> None:
        with self._lock:
            self.conn.rollback()

    def close(self) -> None:
        with self._lock:
            self.conn.commit()
            self.conn.close()

    def __enter__(self) -> "BrainDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def wipe(self) -> None:
        """Factory-reset the brain: wipe learned tables, restore seed genome.

        Only WIPEABLE_TABLES are touched, and each name must be a plain SQL
        identifier (belt-and-braces against future refactoring introducing
        interpolation of untrusted values into DDL/DML).
        """
        for table in sorted(WIPEABLE_TABLES):
            if not table.isidentifier():
                raise ValueError(f"table name is not a plain identifier: {table!r}")
            self.execute(f"DELETE FROM {table}")
        self.execute("UPDATE personas SET active=0")
        self.execute("UPDATE personas SET active=1 WHERE version=1")
        self.commit()
        log.debug("brain wiped; tables reset: %s", ", ".join(sorted(WIPEABLE_TABLES)))

    # -- meta table ---------------------------------------------------------
    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return row["value"] if row else default

    def set_meta(self, key: str, value: Any) -> None:
        """Set a meta value. Caller commits."""
        self.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
