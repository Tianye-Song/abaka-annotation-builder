"""Turning a definition into a running project instance.

Everything here is driven from the admin UI (via api.py):
  * create_project   - YAML text + uploaded data files -> new project
  * update_definition - edited YAML -> same project, new definition version
  * add_files        - upload more items into an existing project

Every project lives in its own folder under var/projects/<slug>/ (data files);
the definition itself is stored in the database. `seed()` loads the example
projects in projects/ once, on first start, so the app isn't empty.
"""
from __future__ import annotations

import fnmatch
import json
import shutil
import sqlite3
import struct
import wave
from functools import lru_cache
from pathlib import Path

import yaml

from . import auth, db
from .definition import DefinitionError, ProjectDef, definition_hash, parse_definition

ROOT = db.ROOT
SEED_PROJECTS = ROOT / "projects"
TEMPLATE_DIRS = [ROOT / "projects", ROOT / "examples"]
SEED_FILE = ROOT / "config" / "seed.yaml"
PROJECTS_HOME = db.DB_PATH.parent / "projects"


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


# --------------------------------------------------------------------- items
def read_items(defn: ProjectDef, project_dir: Path) -> list[tuple[str, dict]]:
    """Return (external_id, payload) for every item currently in the project's data folder."""
    src = defn.data
    base = project_dir / src.path
    out: list[tuple[str, dict]] = []
    if src.kind == "files":
        extra = {}
        if src.meta and (project_dir / src.meta).exists():
            for line in (project_dir / src.meta).read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    extra[row.pop("file")] = row
        for f in sorted(base.glob(src.glob)) if base.is_dir() else []:
            if f.is_file():
                rel = f.relative_to(project_dir).as_posix()
                out.append((f.name, {"media": rel, "meta": {**probe_media(f), **extra.get(f.name, {})}}))
    elif base.is_file():  # jsonl
        for n, line in enumerate(base.read_text().splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
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


def add_files(defn: ProjectDef, project_dir: Path, files: list[tuple[str, bytes]]) -> int:
    """Store uploaded data files where the definition's data source expects them.

    files source: each file must match the glob and is saved into the data folder.
    jsonl source: each uploaded .jsonl is validated and appended to the items file.
    """
    src = defn.data
    if src.kind == "files":
        target = project_dir / src.path
        target.mkdir(parents=True, exist_ok=True)
        for name, content in files:
            safe = Path(name).name
            if not safe or safe.startswith(".") or not fnmatch.fnmatch(safe, src.glob):
                raise DefinitionError([f"'{name}' doesn't match this project's data pattern '{src.glob}'"])
            (target / safe).write_bytes(content)
        return len(files)

    lines: list[str] = []
    for name, content in files:
        for n, line in enumerate(content.decode("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise DefinitionError([f"{name}:{n}: not valid JSON ({e.msg})"]) from None
            if not isinstance(row, dict) or "id" not in row:
                raise DefinitionError([f"{name}:{n}: every line needs an \"id\""])
            lines.append(json.dumps(row))
    target = project_dir / src.path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as f:
        f.writelines(line + "\n" for line in lines)
    return len(lines)


# --------------------------------------------------------------------- users & teams
def add_user(conn: sqlite3.Connection, user_id: str, name: str, roles: list[str], password: str) -> None:
    with db.tx(conn):
        conn.execute("INSERT INTO users(id,name,password_hash) VALUES (?,?,?)", (user_id, name, auth.hash_password(password)))
        set_roles(conn, user_id, roles)


def roles_of(conn: sqlite3.Connection, user_id: str) -> set[str]:
    return {r["role"] for r in conn.execute("SELECT role FROM user_roles WHERE user_id=?", (user_id,))}


def set_roles(conn: sqlite3.Connection, user_id: str, roles: list[str]) -> None:
    """Replace a user's account roles (caller holds the transaction)."""
    conn.execute("DELETE FROM user_roles WHERE user_id=?", (user_id,))
    conn.executemany("INSERT INTO user_roles(user_id, role) VALUES (?,?)", [(user_id, r) for r in sorted(set(roles))])


def add_member(conn: sqlite3.Connection, project_id: int, user_id: str, role: str, created_by: str | None) -> None:
    """Put a user on a project's team as a worker or a reviewer (independent of each other)."""
    conn.execute(
        "INSERT INTO project_members(project_id,user_id,role,created_by,created_at) VALUES (?,?,?,?,?)",
        (project_id, user_id, role, created_by, db.now()),
    )


def _stored(defn: ProjectDef) -> tuple[str, str]:
    """(validated JSON, hash): what the projects row stores for a definition."""
    return db.dumps(defn.model_dump(mode="json")), definition_hash(defn)


# --------------------------------------------------------------------- projects
class Conflict(ValueError):
    pass


def create_project(
    conn: sqlite3.Connection, yaml_text: str, created_by: str | None,
    files: list[tuple[str, bytes]] = (), source_dir: Path | None = None, copy_data_from: str | None = None,
) -> dict:
    """Validate a definition, store its data files and register the project.

    copy_data_from: slug of an existing project whose data files are reused (copied),
    so a new project can label the same data differently without re-uploading it.
    """
    defn = parse_definition(yaml_text)
    if conn.execute("SELECT 1 FROM projects WHERE slug=?", (defn.slug,)).fetchone():
        raise Conflict(f"a project with slug '{defn.slug}' already exists")
    copy_src = None
    if copy_data_from:
        row = conn.execute("SELECT source_dir FROM projects WHERE slug=?", (copy_data_from,)).fetchone()
        if row is None:
            raise Conflict(f"no project '{copy_data_from}' to reuse data from")
        copy_src = Path(row["source_dir"])
    project_dir = source_dir or PROJECTS_HOME / defn.slug
    project_dir.mkdir(parents=True, exist_ok=True)
    if copy_src:
        shutil.copytree(copy_src, project_dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns("project.yaml"))
    stored = add_files(defn, project_dir, list(files)) if files else 0
    with db.tx(conn):
        pid = conn.execute(
            "INSERT INTO projects(slug,name,modality,source_dir,definition_yaml,definition,definition_hash,created_by,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (defn.slug, defn.name, defn.modality, str(project_dir), yaml_text, *_stored(defn), created_by, db.now(), db.now()),
        ).lastrowid
        added = import_items(conn, pid, defn, project_dir)
    return {"slug": defn.slug, "files": stored, "items_added": added}


def update_definition(conn: sqlite3.Connection, slug: str, yaml_text: str) -> dict:
    """Replace a project's definition. Existing submissions keep the hash they were validated against."""
    defn = parse_definition(yaml_text)
    if defn.slug != slug:
        raise DefinitionError([f"slug can't change (was '{slug}', now '{defn.slug}')"])
    row = conn.execute("SELECT id, source_dir, definition_hash FROM projects WHERE slug=?", (slug,)).fetchone()
    definition_json, h = _stored(defn)
    with db.tx(conn):
        conn.execute(
            "UPDATE projects SET name=?, modality=?, definition_yaml=?, definition=?, definition_hash=?, updated_at=? WHERE id=?",
            (defn.name, defn.modality, yaml_text, definition_json, h, db.now(), row["id"]),
        )
        added = import_items(conn, row["id"], defn, Path(row["source_dir"]))
    return {"slug": slug, "changed": h != row["definition_hash"], "hash": h, "items_added": added}


@lru_cache(maxsize=256)  # keyed by the JSON text, so an updated definition is a new cache entry
def _parse(definition_json: str) -> ProjectDef:
    return ProjectDef.model_validate(json.loads(definition_json))


def get_definition(conn: sqlite3.Connection, slug: str) -> tuple[sqlite3.Row, ProjectDef] | None:
    row = conn.execute("SELECT * FROM projects WHERE slug=?", (slug,)).fetchone()
    if row is None:
        return None
    return row, _parse(row["definition"])


def existing_projects(conn: sqlite3.Connection) -> list[dict]:
    """Projects already in the system, for "reuse a previous project" (definition and optionally data)."""
    return [
        {"slug": r["slug"], "name": r["name"], "modality": r["modality"], "yaml": r["definition_yaml"],
         "items": r["items"], "created_by": r["created_by"]}
        for r in conn.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM items i WHERE i.project_id=p.id) items FROM projects p ORDER BY p.created_at DESC, p.name"
        )
    ]


def templates() -> list[dict]:
    """Example definitions shipped in the repo (projects/ and examples/)."""
    out = []
    for d in TEMPLATE_DIRS:
        for f in sorted(d.glob("*/project.yaml")):
            text = f.read_text()
            try:
                meta = yaml.safe_load(text)
                meta["slug"], meta["name"], meta["modality"]
            except (yaml.YAMLError, TypeError, KeyError):
                continue  # a broken example file shouldn't take the whole list down
            has_data = any(p.is_file() and p.name != "project.yaml" for p in f.parent.rglob("*"))
            out.append({"slug": meta["slug"], "name": meta["name"], "modality": meta["modality"], "yaml": text,
                        "sample_data": str(f.parent.relative_to(ROOT)) if has_data else None})
    return out


# --------------------------------------------------------------------- first-run seed
def seed() -> list[str]:
    """Create the example users and projects once. Never overwrites what was changed in the UI."""
    db.init_db()
    cfg = yaml.safe_load(SEED_FILE.read_text()) if SEED_FILE.exists() else {}
    created = []
    with db.closing() as conn:
        for u in cfg.get("users", []):
            if conn.execute("SELECT 1 FROM users WHERE id=?", (u["id"],)).fetchone() is None:
                add_user(conn, u["id"], u["name"], u.get("roles", ["worker"]), u["password"])
        for f in sorted(SEED_PROJECTS.glob("*/project.yaml")):
            slug = yaml.safe_load(f.read_text())["slug"]
            if conn.execute("SELECT 1 FROM projects WHERE slug=?", (slug,)).fetchone():
                continue
            target = PROJECTS_HOME / slug
            shutil.copytree(f.parent, target, dirs_exist_ok=True)  # work on a copy; the repo stays untouched
            team = cfg.get("projects", {}).get(slug, {})
            create_project(conn, f.read_text(), team.get("created_by"), source_dir=target)
            pid = conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)).fetchone()["id"]
            with db.tx(conn):
                for role in ("worker", "reviewer"):
                    for uid in team.get(f"{role}s", []):
                        add_member(conn, pid, uid, role, team.get("created_by"))
            created.append(slug)
    return created
