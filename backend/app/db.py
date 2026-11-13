"""SQLite storage shared by every project.

Project-specific shape lives in JSON columns (items.payload, submissions.data);
everything the workflow depends on (status, assignee, decisions) is relational,
so the same queries serve every project.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("ANNOTATE_DB", ROOT / "var" / "annotate.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id    TEXT PRIMARY KEY,
  name  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  id              INTEGER PRIMARY KEY,
  slug            TEXT UNIQUE NOT NULL,
  name            TEXT NOT NULL,
  modality        TEXT NOT NULL,
  source_dir      TEXT NOT NULL,          -- folder holding project.yaml and data
  definition      TEXT NOT NULL,          -- validated definition snapshot (JSON)
  definition_hash TEXT NOT NULL,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memberships (
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id    TEXT    NOT NULL REFERENCES users(id),
  role       TEXT    NOT NULL CHECK (role IN ('admin','worker','reviewer')),
  PRIMARY KEY (project_id, user_id, role)
);

CREATE TABLE IF NOT EXISTS items (
  id          INTEGER PRIMARY KEY,
  project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  external_id TEXT    NOT NULL,           -- stable id from the data source
  payload     TEXT    NOT NULL,           -- {media?, meta:{...}} as JSON
  created_at  TEXT    NOT NULL,
  UNIQUE (project_id, external_id)
);

-- One task per item. status: assigned -> submitted -> passed | failed -> submitted ...
CREATE TABLE IF NOT EXISTS tasks (
  id          INTEGER PRIMARY KEY,
  project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  item_id     INTEGER NOT NULL UNIQUE REFERENCES items(id) ON DELETE CASCADE,
  status      TEXT    NOT NULL CHECK (status IN ('unassigned','assigned','submitted','failed','passed')),
  assignee    TEXT    REFERENCES users(id),
  draft       TEXT,                       -- worker's unsaved work (JSON)
  created_at  TEXT    NOT NULL,
  updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tasks_project_status ON tasks(project_id, status);
CREATE INDEX IF NOT EXISTS ix_tasks_assignee ON tasks(assignee, status);

-- Every submission is kept, so rework history is never lost.
CREATE TABLE IF NOT EXISTS submissions (
  id              INTEGER PRIMARY KEY,
  task_id         INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  worker_id       TEXT    NOT NULL REFERENCES users(id),
  version         INTEGER NOT NULL,
  data            TEXT    NOT NULL,       -- the annotation, valid against the project's output schema
  check_results   TEXT    NOT NULL,       -- automatic check results at submit time
  definition_hash TEXT    NOT NULL,       -- which definition version it was validated against
  submitted_at    TEXT    NOT NULL,
  UNIQUE (task_id, version)
);

CREATE TABLE IF NOT EXISTS reviews (
  id            INTEGER PRIMARY KEY,
  task_id       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  submission_id INTEGER NOT NULL UNIQUE REFERENCES submissions(id),
  reviewer_id   TEXT    NOT NULL REFERENCES users(id),
  decision      TEXT    NOT NULL CHECK (decision IN ('pass','fail')),
  comment       TEXT    NOT NULL DEFAULT '',
  checklist     TEXT    NOT NULL DEFAULT '{}',
  created_at    TEXT    NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    with closing() as c:
        c.executescript(SCHEMA)


@contextmanager
def closing():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def tx(conn: sqlite3.Connection):
    """Explicit transaction (connections run in autocommit mode otherwise)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def loads(s: str | None):
    return None if s is None else json.loads(s)


def dumps(v) -> str:
    return json.dumps(v, separators=(",", ":"))
