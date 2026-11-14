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

SCHEMA_VERSION = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id    TEXT PRIMARY KEY,
  name  TEXT NOT NULL,
  password_hash TEXT NOT NULL                -- salted PBKDF2 (see auth.py), never the password itself
);

-- What an account may do, granted by an admin. A user can hold several:
--   admin    creates projects, manages users and teams, administers every project
--   worker   can be put on a project's team and assigned labeling jobs
--   reviewer can be paired with workers to review their submissions
CREATE TABLE IF NOT EXISTS user_roles (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role    TEXT NOT NULL CHECK (role IN ('admin','worker','reviewer')),
  PRIMARY KEY (user_id, role)
);

-- Logged-in sessions: the token the browser sends as "Authorization: Bearer <token>".
CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL
);

-- A project = one annotation platform instance: its definition (schema), its items/tasks, its status.
CREATE TABLE IF NOT EXISTS projects (
  id              INTEGER PRIMARY KEY,
  slug            TEXT UNIQUE NOT NULL,
  name            TEXT NOT NULL,
  modality        TEXT NOT NULL,          -- the project's data category: audio | image | text | code
  status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','archived')),
  source_dir      TEXT NOT NULL,          -- folder holding the project's data files
  definition_yaml TEXT NOT NULL,          -- what the admin wrote
  definition      TEXT NOT NULL,          -- validated definition (JSON)
  definition_hash TEXT NOT NULL,
  created_by      TEXT REFERENCES users(id),
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);

-- Who works on a project: workers and reviewers, independently (no fixed pairs).
-- Which reviewer checks a task is chosen when the task is assigned (tasks.reviewer_id).
CREATE TABLE IF NOT EXISTS project_members (
  project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id     TEXT    NOT NULL REFERENCES users(id),
  role        TEXT    NOT NULL CHECK (role IN ('worker','reviewer')),
  created_by  TEXT    REFERENCES users(id),
  created_at  TEXT    NOT NULL,
  PRIMARY KEY (project_id, user_id, role)
);

-- Every (project, user, role) triple, derived: admins (account admins or the project creator),
-- plus the project's workers and reviewers.
CREATE VIEW IF NOT EXISTS project_roles AS
  SELECT p.id AS project_id, u.id AS user_id, 'admin' AS role
    FROM projects p JOIN users u
      ON u.id = p.created_by OR EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id = u.id AND ur.role = 'admin')
  UNION SELECT project_id, user_id, role FROM project_members;

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
  assignee    TEXT    REFERENCES users(id),   -- the worker
  reviewer_id TEXT    REFERENCES users(id),   -- the reviewer, chosen when the task is assigned
  draft       TEXT,                       -- worker's unsaved work (JSON)
  created_at  TEXT    NOT NULL,
  updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tasks_project_status ON tasks(project_id, status);
CREATE INDEX IF NOT EXISTS ix_tasks_assignee ON tasks(assignee, status);
CREATE INDEX IF NOT EXISTS ix_tasks_reviewer ON tasks(reviewer_id, status);

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


class SchemaMismatch(RuntimeError):
    pass


def _migrate_3_to_4(c: sqlite3.Connection) -> None:
    """One role per account (users.role) -> any set of roles (user_roles). Keeps all data."""
    c.executescript(
        """
        BEGIN;
        DROP VIEW IF EXISTS project_roles;  -- it reads users.role; recreated from SCHEMA below
        CREATE TABLE user_roles (
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          role    TEXT NOT NULL CHECK (role IN ('admin','worker','reviewer')),
          PRIMARY KEY (user_id, role)
        );
        INSERT INTO user_roles(user_id, role) SELECT id, role FROM users;
        ALTER TABLE users DROP COLUMN role;
        COMMIT;
        """
    )


def _migrate_4_to_5(c: sqlite3.Connection) -> None:
    """Worker->reviewer pairs (project_assignments) -> independent members (project_members).
    Existing tasks keep the reviewer they were routed to."""
    c.executescript(
        """
        BEGIN;
        DROP VIEW IF EXISTS project_roles;  -- recreated from SCHEMA below
        CREATE TABLE project_members (
          project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          user_id     TEXT    NOT NULL REFERENCES users(id),
          role        TEXT    NOT NULL CHECK (role IN ('worker','reviewer')),
          created_by  TEXT    REFERENCES users(id),
          created_at  TEXT    NOT NULL,
          PRIMARY KEY (project_id, user_id, role)
        );
        INSERT OR IGNORE INTO project_members SELECT project_id, worker_id, 'worker', created_by, created_at FROM project_assignments;
        INSERT OR IGNORE INTO project_members SELECT project_id, reviewer_id, 'reviewer', created_by, created_at FROM project_assignments;
        DROP TABLE project_assignments;
        COMMIT;
        """
    )


MIGRATIONS = {3: _migrate_3_to_4, 4: _migrate_4_to_5}


def init_db() -> None:
    with closing() as c:
        version = c.execute("PRAGMA user_version").fetchone()[0]
        has_tables = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        while has_tables and version in MIGRATIONS:
            MIGRATIONS[version](c)
            version += 1
            c.execute(f"PRAGMA user_version = {version}")
        if has_tables and version != SCHEMA_VERSION:
            raise SchemaMismatch(f"database at {DB_PATH} uses an old schema; run ./annotate reset")
        c.executescript(SCHEMA)
        c.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


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
