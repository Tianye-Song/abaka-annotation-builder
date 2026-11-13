"""Turning a definition folder into a running project instance.

`create_project(folder)` is the whole "mechanism" from the operator's side:
validate the definition, register (or update) the project, its members and its
items. Everything else - views, workflow, storage, validation - is shared code
that reads the definition at runtime.
"""
from __future__ import annotations

import json
import sqlite3
import struct
import wave
from functools import lru_cache
from pathlib import Path

import yaml

from . import db
from .definition import ProjectDef, definition_hash, load_definition

ROOT = db.ROOT
PROJECTS_DIR = ROOT / "projects"
USERS_FILE = ROOT / "config" / "users.yaml"


# --------------------------------------------------------------------- media probe
def probe_media(path: Path) -> dict:
    """Cheap metadata the checks rely on (clip duration, image size). No heavy deps."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".wav":
            with wave.open(str(path)) as w:
                return {"duration": round(w.getnframes() / w.getframerate(), 3)}
        if suffix == ".png":
            with path.open("rb") as f:
                head = f.read(24)
            w, h = struct.unpack(">II", head[16:24])
            return {"width": w, "height": h}
    except (OSError, wave.Error, struct.error):
        pass
    return {}


# --------------------------------------------------------------------- item loading
def read_items(defn: ProjectDef, project_dir: Path) -> list[tuple[str, dict]]:
    """Return (external_id, payload) for every item in the project's data source."""
    src = defn.data
    base = project_dir / src.path
    out: list[tuple[str, dict]] = []
    if src.kind == "files":
        extra = {}
        if src.meta:
            for line in (project_dir / src.meta).read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    extra[row.pop("file")] = row
        for f in sorted(base.glob(src.glob)):
            if f.is_file():
                rel = f.relative_to(project_dir).as_posix()
                meta = {**probe_media(f), **extra.get(f.name, {})}
                out.append((f.name, {"media": rel, "meta": meta}))
    else:  # jsonl
        for n, line in enumerate(base.read_text().splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if "id" not in row:
                raise ValueError(f"{base}:{n}: every jsonl item needs an 'id'")
            ext_id = str(row.pop("id"))
            media = row.pop("media", None)
            out.append((ext_id, {"media": media, "meta": row}))
    return out


def import_items(conn: sqlite3.Connection, project_id: int, defn: ProjectDef, project_dir: Path) -> int:
    """Insert items not seen before (idempotent: re-running only adds new ones)."""
    added = 0
    for ext_id, payload in read_items(defn, project_dir):
        cur = conn.execute(
            "INSERT OR IGNORE INTO items(project_id, external_id, payload, created_at) VALUES (?,?,?,?)",
            (project_id, ext_id, db.dumps(payload), db.now()),
        )
        added += cur.rowcount
    return added


# --------------------------------------------------------------------- users
def sync_users(conn: sqlite3.Connection) -> None:
    if USERS_FILE.exists():
        for u in yaml.safe_load(USERS_FILE.read_text()) or []:
            conn.execute(
                "INSERT INTO users(id, name) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name",
                (u["id"], u["name"]),
            )


# --------------------------------------------------------------------- create / update
def create_project(project_dir: Path) -> dict:
    """Validate a definition folder and stand up (or update) its project instance."""
    project_dir = project_dir.resolve()
    defn = load_definition(project_dir)
    h = definition_hash(defn)
    db.init_db()
    with db.closing() as conn, db.tx(conn):
        sync_users(conn)
        row = conn.execute("SELECT id, definition_hash FROM projects WHERE slug=?", (defn.slug,)).fetchone()
        payload = db.dumps(defn.model_dump(mode="json"))
        if row is None:
            pid = conn.execute(
                "INSERT INTO projects(slug,name,modality,source_dir,definition,definition_hash,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (defn.slug, defn.name, defn.modality, str(project_dir), payload, h, db.now(), db.now()),
            ).lastrowid
            action = "created"
        else:
            pid = row["id"]
            conn.execute(
                "UPDATE projects SET name=?, modality=?, source_dir=?, definition=?, definition_hash=?, updated_at=?"
                " WHERE id=?",
                (defn.name, defn.modality, str(project_dir), payload, h, db.now(), pid),
            )
            action = "unchanged" if row["definition_hash"] == h else "updated"

        # Members: the definition is the source of truth, so replace them.
        conn.execute("DELETE FROM memberships WHERE project_id=?", (pid,))
        new_users = []
        for user, role in defn.member_roles():
            if conn.execute("SELECT 1 FROM users WHERE id=?", (user,)).fetchone() is None:
                conn.execute("INSERT INTO users(id, name) VALUES (?,?)", (user, user.title()))
                new_users.append(user)
            conn.execute("INSERT INTO memberships(project_id,user_id,role) VALUES (?,?,?)", (pid, user, role))

        added = import_items(conn, pid, defn, project_dir)
        total = conn.execute("SELECT COUNT(*) FROM items WHERE project_id=?", (pid,)).fetchone()[0]
    return {
        "slug": defn.slug,
        "action": action,
        "items_added": added,
        "items_total": total,
        "members": defn.member_roles(),
        "new_users": new_users,
        "hash": h,
    }


def discover() -> list[Path]:
    return sorted(p.parent for p in PROJECTS_DIR.glob("*/project.yaml"))


@lru_cache(maxsize=256)  # keyed by the JSON text, so an updated definition is a new cache entry
def _parse(definition_json: str) -> ProjectDef:
    return ProjectDef.model_validate(json.loads(definition_json))


def get_definition(conn: sqlite3.Connection, slug: str) -> tuple[sqlite3.Row, ProjectDef] | None:
    row = conn.execute("SELECT * FROM projects WHERE slug=?", (slug,)).fetchone()
    if row is None:
        return None
    return row, _parse(row["definition"])

