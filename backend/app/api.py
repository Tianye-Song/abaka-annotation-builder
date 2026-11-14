"""HTTP API shared by every project; every operation the UI offers goes through here.

Nothing here knows about audio, images or code: project-specific behaviour comes
from the definition (schema, checks, review rules).
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field

from . import auth, db, lifecycle, registry
from .checks import CHECKS, run_checks
from .definition import DefinitionError, ProjectDef, Role, output_schema, parse_definition
from .fields import FIELD_TYPES, NOT_BLANK

router = APIRouter(prefix="/api")

# The review of a task's latest submission (NULL columns if it has none yet); joined as `lr`.
LATEST_REVIEW = "LEFT JOIN reviews lr ON lr.submission_id=(SELECT MAX(s.id) FROM submissions s WHERE s.task_id=t.id)"
VERSIONS = "(SELECT COUNT(*) FROM submissions s WHERE s.task_id=t.id) versions"


# ----------------------------------------------------------------- dependencies
def get_conn():
    with db.closing() as conn:
        yield conn


def bearer(authorization: str) -> str:
    return authorization.removeprefix("Bearer ").strip()


@dataclass
class Me:
    id: str
    name: str
    roles: set[str]  # account roles (user_roles): what this user may do anywhere

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    def json(self) -> dict:
        return {"id": self.id, "name": self.name, "roles": sorted(self.roles)}


def load_me(conn: sqlite3.Connection, row: sqlite3.Row) -> Me:
    return Me(row["id"], row["name"], registry.roles_of(conn, row["id"]))


def get_me(authorization: str = Header("", description="Bearer <session token> from /api/login"), conn=Depends(get_conn)) -> Me:
    token = bearer(authorization)
    row = conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?", (token,)
    ).fetchone() if token else None
    if row is None:
        raise HTTPException(401, "not signed in")
    return load_me(conn, row)


def require_admin(me: Me = Depends(get_me)) -> Me:
    if not me.is_admin:
        raise HTTPException(403, "only an admin can do this")
    return me


@dataclass
class Ctx:
    conn: sqlite3.Connection
    me: Me
    project: sqlite3.Row
    defn: ProjectDef
    roles: set[str]

    @property
    def user(self) -> str:
        return self.me.id

    def need(self, role: str) -> None:
        if role not in self.roles:
            raise HTTPException(403, f"you are not a {role} on {self.defn.slug}")

    def need_active(self) -> None:
        if self.project["status"] != "active":
            raise HTTPException(409, f"project is {self.project['status']}")


def load_ctx(conn: sqlite3.Connection, me: Me, slug: str) -> Ctx:
    found = registry.get_definition(conn, slug)
    if found is None:
        raise HTTPException(404, f"no project '{slug}'")
    row, defn = found
    roles = {r["role"] for r in conn.execute("SELECT role FROM project_roles WHERE project_id=? AND user_id=?", (row["id"], me.id))}
    if not roles:
        raise HTTPException(403, "you are not a member of this project")
    return Ctx(conn, me, row, defn, roles)


def project_ctx(slug: str, me: Me = Depends(get_me), conn=Depends(get_conn)) -> Ctx:
    return load_ctx(conn, me, slug)


def task_ctx(task_id: int, me: Me = Depends(get_me), conn=Depends(get_conn)) -> tuple[Ctx, sqlite3.Row]:
    task = conn.execute(
        "SELECT t.*, p.slug FROM tasks t JOIN projects p ON p.id=t.project_id WHERE t.id=?", (task_id,)
    ).fetchone()
    if task is None:
        raise HTTPException(404, "no such task")
    ctx = load_ctx(conn, me, task["slug"])
    # Workers only see their own tasks; admins and reviewers see all tasks in the project.
    if not ctx.roles & {"admin", "reviewer"} and task["assignee"] != me.id:
        raise HTTPException(403, "this task is not assigned to you")
    return ctx, task


def definition_errors(e: DefinitionError) -> HTTPException:
    return HTTPException(422, {"problems": e.problems})


async def read_uploads(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    return [(f.filename or "", await f.read()) for f in files if f.filename]


# ----------------------------------------------------------------- validation
_validators: dict[str, Draft202012Validator] = {}


def validate_annotation(ctx: Ctx, data: dict, item_meta: dict) -> tuple[list[str], list[dict]]:
    """Schema errors first; quality checks only run on structurally valid data."""
    h = ctx.project["definition_hash"]
    if h not in _validators:
        _validators[h] = Draft202012Validator(output_schema(ctx.defn))
    errors = [
        f"{'/'.join(map(str, e.absolute_path)) or 'annotation'}: "
        + ("must not be blank" if e.validator == "pattern" and e.validator_value == NOT_BLANK else e.message)
        for e in _validators[h].iter_errors(data)
    ]
    checks = [] if errors else run_checks(ctx.defn, data, item_meta)
    return errors, checks


# ----------------------------------------------------------------- serializers
def media_url(slug: str, media: str | None) -> str | None:
    if not media:
        return None
    return media if media.startswith(("http://", "https://")) else f"/media/{slug}/{media}"


def item_json(slug: str, row: sqlite3.Row) -> dict:
    payload = db.loads(row["payload"])
    return {"id": row["id"], "external_id": row["external_id"], "media_url": media_url(slug, payload.get("media")), "meta": payload.get("meta", {})}


def project_summary(row: sqlite3.Row) -> dict:
    return {"slug": row["slug"], "name": row["name"], "modality": row["modality"], "status": row["status"]}


def derived_summary(defn: ProjectDef) -> dict:
    """What the platform generates from a definition (shown before creating)."""
    return {
        "slug": defn.slug,
        "name": defn.name,
        "modality": defn.modality,
        "fields": [{"id": f.id, "type": f.type, "label": f.label or f.id, "required": f.required} for f in defn.task.fields],
        "checks": [f"{c.check} on {c.parsed.field} ({c.severity})" for c in defn.task.checks],
        "checklist": defn.review.checklist,
        "data": defn.data.model_dump(),
        "output_schema": output_schema(defn),
    }


# ----------------------------------------------------------------- login
@router.get("/accounts")
def accounts(conn=Depends(get_conn)):
    """Names for the login dropdown (no roles, no project details)."""
    return [{"id": r["id"], "name": r["name"]} for r in conn.execute("SELECT id, name FROM users ORDER BY id")]


class LoginBody(BaseModel):
    user_id: str
    password: str


@router.post("/login")
def login(body: LoginBody, conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM users WHERE id=?", (body.user_id,)).fetchone()
    if row is None or not auth.verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "wrong account or password")
    token = auth.new_token()
    conn.execute("INSERT INTO sessions(token,user_id,created_at) VALUES (?,?,?)", (token, row["id"], db.now()))
    return {"token": token, "user": load_me(conn, row).json()}


@router.post("/logout")
def logout(authorization: str = Header(""), conn=Depends(get_conn)):
    conn.execute("DELETE FROM sessions WHERE token=?", (bearer(authorization),))
    return {"ok": True}


# ----------------------------------------------------------------- users
@router.get("/users")
def list_users(_: Me = Depends(require_admin), conn=Depends(get_conn)):
    """User admin: every user, their account roles and their role in each project."""
    users = {r["id"]: {"id": r["id"], "name": r["name"], "roles": [], "projects": []} for r in conn.execute("SELECT * FROM users ORDER BY id")}
    for r in conn.execute("SELECT user_id, role FROM user_roles ORDER BY role"):
        users[r["user_id"]]["roles"].append(r["role"])
    for m in conn.execute(
        "SELECT r.user_id, r.role, p.slug, p.name FROM project_roles r JOIN projects p ON p.id=r.project_id ORDER BY p.slug, r.role"
    ):
        users[m["user_id"]]["projects"].append({"slug": m["slug"], "name": m["name"], "role": m["role"]})
    return list(users.values())


@router.get("/me")
def whoami(me: Me = Depends(get_me)):
    return me.json()


Roles = list[Role]


class NewUser(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    name: str = Field(min_length=1)
    roles: Roles = Field(default=["worker"], min_length=1)
    password: str = Field(min_length=6)


@router.post("/users")
def create_user(body: NewUser, _: Me = Depends(require_admin), conn=Depends(get_conn)):
    if conn.execute("SELECT 1 FROM users WHERE id=?", (body.id,)).fetchone():
        raise HTTPException(409, f"user '{body.id}' already exists")
    registry.add_user(conn, body.id, body.name.strip(), body.roles, body.password)
    return {"ok": True}


class UserPatch(BaseModel):
    name: str | None = None
    roles: Roles | None = Field(default=None, min_length=1)
    password: str | None = Field(default=None, min_length=6)


@router.patch("/users/{user_id}")
def update_user(user_id: str, body: UserPatch, me: Me = Depends(require_admin), conn=Depends(get_conn)):
    if conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is None:
        raise HTTPException(404, f"no user '{user_id}'")
    if body.roles is not None:
        removed = registry.roles_of(conn, user_id) - set(body.roles)
        if user_id == me.id and "admin" in removed:
            raise HTTPException(400, "you can't remove your own admin role")
        for role in removed & {"worker", "reviewer"}:  # an admin needs no team seat
            teams = [r["slug"] for r in conn.execute(
                "SELECT p.slug FROM project_members m JOIN projects p ON p.id=m.project_id WHERE m.user_id=? AND m.role=? ORDER BY p.slug",
                (user_id, role),
            )]
            if teams:
                raise HTTPException(409, f"{user_id} is a {role} on {', '.join(teams)}; take them off those teams first")
    with db.tx(conn):
        if body.name:
            conn.execute("UPDATE users SET name=? WHERE id=?", (body.name.strip(), user_id))
        if body.roles is not None:
            registry.set_roles(conn, user_id, body.roles)
        if body.password:
            conn.execute("UPDATE users SET password_hash=? WHERE id=?", (auth.hash_password(body.password), user_id))
            conn.execute("DELETE FROM sessions WHERE user_id=? AND user_id<>?", (user_id, me.id))  # sign them out elsewhere
    return {"ok": True}


@router.delete("/users/{user_id}")
def delete_user(user_id: str, me: Me = Depends(require_admin), conn=Depends(get_conn)):
    """Delete an account. Refused while they're on a team or have work on record (tasks,
    submissions, reviews, projects they created), so history stays intact; take away their roles instead."""
    if user_id == me.id:
        raise HTTPException(400, "you can't delete your own account")
    if conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is None:
        raise HTTPException(404, f"no user '{user_id}'")
    teams = [r["slug"] for r in conn.execute(
        "SELECT DISTINCT p.slug FROM project_members m JOIN projects p ON p.id=m.project_id WHERE m.user_id=? ORDER BY p.slug", (user_id,))]
    if teams:
        raise HTTPException(409, f"{user_id} is on the team of {', '.join(teams)}; remove them there first")
    try:
        with db.tx(conn):
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))  # sessions and account roles go with it
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"{user_id} has tasks or reviews on record, so the account is kept; remove their roles instead")
    return {"ok": True}


# ----------------------------------------------------------------- portal
@router.get("/me/projects")
def my_projects(me: Me = Depends(get_me), conn=Depends(get_conn)):
    """Unified portal: every project the user can access, their roles, and what's waiting for them."""
    rows = conn.execute(
        "SELECT p.*, group_concat(r.role) AS roles FROM projects p JOIN project_roles r ON r.project_id=p.id"
        " WHERE r.user_id=? GROUP BY p.id ORDER BY p.status, p.name",
        (me.id,),
    ).fetchall()
    out = []
    for p in rows:
        counts = conn.execute(
            """SELECT
                 COALESCE(SUM(status='assigned'  AND assignee=:u),0)    AS todo,
                 COALESCE(SUM(status='failed'    AND assignee=:u),0)    AS rework,
                 COALESCE(SUM(status='submitted' AND reviewer_id=:u),0) AS to_review,
                 COALESCE(SUM(status='unassigned'),0)                   AS unassigned,
                 COALESCE(SUM(status='passed'),0)                       AS passed,
                 COUNT(*)                                               AS tasks
               FROM tasks WHERE project_id=:p""",
            {"u": me.id, "p": p["id"]},
        ).fetchone()
        out.append({**project_summary(p), "roles": sorted(set(p["roles"].split(","))), "counts": dict(counts)})
    return out


# ----------------------------------------------------------------- create / edit projects
@router.get("/templates")
def list_templates(_: Me = Depends(require_admin), conn=Depends(get_conn)):
    """What a new project can start from: previously created projects (reuse definition and
    optionally data) and the example definitions shipped with the repo."""
    return {"projects": registry.existing_projects(conn), "examples": registry.templates()}


@router.get("/field-types")
def field_types():
    """The building blocks a definition can use (reference panel in the project editor)."""
    return {
        "fields": {n: {"modalities": sorted(t.modalities), "params": list(t.Params.model_fields)} for n, t in FIELD_TYPES.items()},
        "checks": {n: {"params": [p for p in m.model_fields if p != "field"], "applies_to": sorted(a) if a else None} for n, (m, _, a) in CHECKS.items()},
    }


class DefinitionBody(BaseModel):
    yaml: str


@router.post("/projects/validate")
def validate_definition(body: DefinitionBody, _: Me = Depends(get_me)):
    """Dry run: is this definition usable, and what would the platform generate from it?"""
    try:
        return {"ok": True, "derived": derived_summary(parse_definition(body.yaml))}
    except DefinitionError as e:
        return {"ok": False, "problems": e.problems}


@router.post("/projects")
async def create_project(
    definition: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    copy_data_from: str = Form(""),
    me: Me = Depends(require_admin),
    conn=Depends(get_conn),
):
    """New project from the admin UI: the definition YAML plus uploaded data files and/or the
    data of a previously created project (copy_data_from = its slug)."""
    try:
        return registry.create_project(conn, definition, me.id, await read_uploads(files), copy_data_from=copy_data_from or None)
    except registry.Conflict as e:
        raise HTTPException(409, {"problems": [str(e)]})
    except DefinitionError as e:
        raise definition_errors(e)


@router.put("/projects/{slug}/definition")
def update_definition(body: DefinitionBody, ctx: Ctx = Depends(project_ctx)):
    ctx.need("admin")
    try:
        return registry.update_definition(ctx.conn, ctx.defn.slug, body.yaml)
    except DefinitionError as e:
        raise definition_errors(e)


class StatusBody(BaseModel):
    status: Literal["active", "paused", "archived"]


@router.put("/projects/{slug}/status")
def set_status(body: StatusBody, ctx: Ctx = Depends(project_ctx)):
    ctx.need("admin")
    ctx.conn.execute("UPDATE projects SET status=?, updated_at=? WHERE id=?", (body.status, db.now(), ctx.project["id"]))
    return {"status": body.status}


@router.post("/projects/{slug}/items/upload")
async def upload_items(files: list[UploadFile] = File(...), ctx: Ctx = Depends(project_ctx)):
    """Add data to an existing project: media files, or a .jsonl of text items."""
    ctx.need("admin")
    project_dir = Path(ctx.project["source_dir"])
    try:
        stored = registry.add_files(ctx.defn, project_dir, await read_uploads(files))
    except DefinitionError as e:
        raise definition_errors(e)
    with db.tx(ctx.conn):
        added = registry.import_items(ctx.conn, ctx.project["id"], ctx.defn, project_dir)
    return {"stored": stored, "added": added}


# ----------------------------------------------------------------- project read
@router.get("/projects/{slug}")
def get_project(ctx: Ctx = Depends(project_ctx)):
    members = defaultdict(list)
    for m in ctx.conn.execute(
        "SELECT r.user_id, u.name, r.role FROM project_roles r JOIN users u ON u.id=r.user_id WHERE project_id=? ORDER BY u.id",
        (ctx.project["id"],),
    ):
        members[m["role"]].append({"id": m["user_id"], "name": m["name"]})
    return {
        **project_summary(ctx.project),
        "description": ctx.defn.description,
        "created_by": ctx.project["created_by"],
        "created_at": ctx.project["created_at"],
        "definition": ctx.defn.model_dump(mode="json"),
        # The YAML and schema are for admins; workers and reviewers only get the parsed definition the task page renders.
        "definition_yaml": ctx.project["definition_yaml"] if "admin" in ctx.roles else None,
        "definition_hash": ctx.project["definition_hash"],
        "output_schema": output_schema(ctx.defn) if "admin" in ctx.roles else None,
        "roles": sorted(ctx.roles),
        "members": members,  # {admin: [...], worker: [...], reviewer: [...]}
    }


# ----------------------------------------------------------------- team (project_members)
class MemberBody(BaseModel):
    user_id: str
    role: Literal["worker", "reviewer"]


@router.post("/projects/{slug}/members")
def add_member(body: MemberBody, ctx: Ctx = Depends(project_ctx)):
    """Put a worker or a reviewer on the project. Workers and reviewers are independent: the
    reviewer of each task is chosen when it is assigned."""
    ctx.need("admin")
    if ctx.conn.execute("SELECT 1 FROM users WHERE id=?", (body.user_id,)).fetchone() is None:
        raise HTTPException(400, f"unknown user '{body.user_id}'")
    if body.role not in registry.roles_of(ctx.conn, body.user_id):
        raise HTTPException(400, f"{body.user_id} doesn't have the {body.role} role (an admin can grant it on the Users page)")
    try:
        registry.add_member(ctx.conn, ctx.project["id"], body.user_id, body.role, ctx.user)
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"{body.user_id} is already a {body.role} on this project")
    return {"ok": True}


@router.delete("/projects/{slug}/members/{role}/{user_id}")
def remove_member(role: Literal["worker", "reviewer"], user_id: str, ctx: Ctx = Depends(project_ctx)):
    ctx.need("admin")
    col = "assignee" if role == "worker" else "reviewer_id"
    open_tasks = ctx.conn.execute(
        f"SELECT COUNT(*) FROM tasks WHERE project_id=? AND {col}=? AND status IN {lifecycle.OPEN_SQL}",
        (ctx.project["id"], user_id),
    ).fetchone()[0]
    if open_tasks:
        raise HTTPException(409, f"{user_id} still has {open_tasks} open task(s) as {role}")
    n = ctx.conn.execute("DELETE FROM project_members WHERE project_id=? AND user_id=? AND role=?",
                         (ctx.project["id"], user_id, role)).rowcount
    if not n:
        raise HTTPException(404, f"{user_id} is not a {role} on this project")
    return {"ok": True}


# ----------------------------------------------------------------- admin
@router.get("/projects/{slug}/overview")
def overview(ctx: Ctx = Depends(project_ctx)):
    ctx.need("admin")
    pid = ctx.project["id"]
    c = ctx.conn
    by_status = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM tasks WHERE project_id=? GROUP BY status", (pid,))}
    n_items = c.execute("SELECT COUNT(*) FROM items WHERE project_id=?", (pid,)).fetchone()[0]
    rv = c.execute(
        """SELECT COUNT(*) n, SUM(r.decision='pass') passes,
                  SUM(s.version=1) first_n, SUM(s.version=1 AND r.decision='pass') first_passes
           FROM reviews r JOIN submissions s ON s.id=r.submission_id JOIN tasks t ON t.id=r.task_id
           WHERE t.project_id=?""",
        (pid,),
    ).fetchone()
    workers = c.execute(
        """SELECT m.user_id id, u.name,
             COALESCE(t.assigned,0) assigned, COALESCE(t.passed,0) passed, COALESCE(t.open,0) open,
             COALESCE(r.reviews,0) reviews, COALESCE(r.review_passes,0) review_passes
           FROM project_members m JOIN users u ON u.id=m.user_id
           LEFT JOIN (SELECT assignee, COUNT(*) assigned, SUM(status='passed') passed, SUM(status IN ('assigned','failed')) open
                      FROM tasks WHERE project_id=:p GROUP BY assignee) t ON t.assignee=m.user_id
           LEFT JOIN (SELECT t.assignee, COUNT(*) reviews, SUM(r.decision='pass') review_passes
                      FROM reviews r JOIN tasks t ON t.id=r.task_id WHERE t.project_id=:p GROUP BY t.assignee) r ON r.assignee=m.user_id
           WHERE m.project_id=:p AND m.role='worker' ORDER BY m.user_id""",
        {"p": pid},
    ).fetchall()
    reviewers = c.execute(
        """SELECT m.user_id id, u.name,
             COALESCE(t.assigned,0) assigned, COALESCE(t.waiting,0) waiting,
             COALESCE(r.reviewed,0) reviewed, COALESCE(r.passes,0) passes, COALESCE(r.fails,0) fails
           FROM project_members m JOIN users u ON u.id=m.user_id
           LEFT JOIN (SELECT reviewer_id, COUNT(*) assigned, SUM(status='submitted') waiting
                      FROM tasks WHERE project_id=:p GROUP BY reviewer_id) t ON t.reviewer_id=m.user_id
           LEFT JOIN (SELECT r.reviewer_id, COUNT(*) reviewed, SUM(r.decision='pass') passes, SUM(r.decision='fail') fails
                      FROM reviews r JOIN tasks t ON t.id=r.task_id WHERE t.project_id=:p GROUP BY r.reviewer_id) r ON r.reviewer_id=m.user_id
           WHERE m.project_id=:p AND m.role='reviewer' ORDER BY m.user_id""",
        {"p": pid},
    ).fetchall()
    rows = c.execute(
        f"""SELECT i.*, t.id task_id, t.status, t.assignee, t.reviewer_id, t.updated_at, {VERSIONS}, lr.decision last_decision
           FROM items i LEFT JOIN tasks t ON t.item_id=i.id {LATEST_REVIEW} WHERE i.project_id=? ORDER BY i.id""",
        (pid,),
    ).fetchall()
    rate = lambda a, b: (a / b) if b else None  # noqa: E731
    return {
        "status": ctx.project["status"],
        "items": n_items,
        "status_counts": {s: by_status.get(s, 0) for s in ("unassigned", "assigned", "submitted", "failed", "passed")},
        "no_task": n_items - sum(by_status.values()),
        "reviews": rv["n"],
        "pass_rate": rate(rv["passes"] or 0, rv["n"]),
        "first_pass_rate": rate(rv["first_passes"] or 0, rv["first_n"] or 0),
        "workers": [{**dict(w), "pass_rate": rate(w["review_passes"], w["reviews"])} for w in workers],
        "reviewers": [{**dict(r), "pass_rate": rate(r["passes"], r["reviewed"])} for r in reviewers],
        "rows": [
            {
                "item": item_json(ctx.defn.slug, r),
                "task_id": r["task_id"], "status": r["status"], "assignee": r["assignee"], "reviewer_id": r["reviewer_id"],
                "versions": r["versions"], "last_decision": r["last_decision"], "updated_at": r["updated_at"],
            }
            for r in rows
        ],
    }


class CreateTasks(BaseModel):
    item_ids: list[int] | None = None  # None = every item that has no task yet


@router.post("/projects/{slug}/tasks")
def create_tasks(body: CreateTasks, ctx: Ctx = Depends(project_ctx)):
    ctx.need("admin")
    pid = ctx.project["id"]
    q = "SELECT i.id FROM items i LEFT JOIN tasks t ON t.item_id=i.id WHERE i.project_id=? AND t.id IS NULL"
    candidates = [r["id"] for r in ctx.conn.execute(q, (pid,))]
    ids = candidates if body.item_ids is None else [i for i in body.item_ids if i in set(candidates)]
    with db.tx(ctx.conn):
        for item_id in ids:
            ctx.conn.execute(
                "INSERT INTO tasks(project_id,item_id,status,created_at,updated_at) VALUES (?,?,'unassigned',?,?)",
                (pid, item_id, db.now(), db.now()),
            )
    return {"created": len(ids)}


class Assign(BaseModel):
    task_ids: list[int]
    worker: str | None = None    # None = the least-loaded worker on the team
    reviewer: str | None = None  # None = the least-loaded reviewer (never the task's own worker)


@router.post("/projects/{slug}/tasks/assign")
def assign_tasks(body: Assign, ctx: Ctx = Depends(project_ctx)):
    """Give tasks to a worker and a reviewer, chosen independently from the team."""
    ctx.need("admin")
    ctx.need_active()
    pid = ctx.project["id"]
    team = {"worker": set(), "reviewer": set()}
    for m in ctx.conn.execute("SELECT user_id, role FROM project_members WHERE project_id=?", (pid,)):
        team[m["role"]].add(m["user_id"])
    for role, chosen in (("worker", body.worker), ("reviewer", body.reviewer)):
        if not team[role]:
            raise HTTPException(400, f"add a {role} to the team first")
        if chosen is not None and chosen not in team[role]:
            raise HTTPException(400, f"{chosen} is not a {role} on this project")

    def open_load(col: str, people: set[str]) -> dict[str, int]:
        load = dict.fromkeys(people, 0)
        for r in ctx.conn.execute(
            f"SELECT {col} who, COUNT(*) n FROM tasks WHERE project_id=? AND status IN {lifecycle.OPEN_SQL} AND {col} IS NOT NULL GROUP BY {col}",
            (pid,),
        ):
            if r["who"] in load:
                load[r["who"]] = r["n"]
        return load

    wload, rload = open_load("assignee", team["worker"]), open_load("reviewer_id", team["reviewer"])
    least = lambda load, skip=None: min((p for p in load if p != skip), key=lambda p: (load[p], p), default=None)  # noqa: E731
    assigned = []
    with db.tx(ctx.conn):
        for tid in body.task_ids:
            t = ctx.conn.execute("SELECT * FROM tasks WHERE id=? AND project_id=?", (tid, pid)).fetchone()
            if t is None:
                raise HTTPException(404, f"no task {tid} in this project")
            new_status = lifecycle.advance(t["status"], "assign", ctx.roles)
            who = body.worker or least(wload)
            rev = body.reviewer or least(rload, skip=who)
            if rev is None or rev == who:
                raise HTTPException(400, f"{who} can't review their own task; pick or add another reviewer")
            wload[who] += 1
            rload[rev] += 1
            ctx.conn.execute(
                "UPDATE tasks SET status=?, assignee=?, reviewer_id=?, updated_at=? WHERE id=?",
                (new_status, who, rev, db.now(), tid),
            )
            assigned.append({"task_id": tid, "worker": who, "reviewer": rev})
    return {"assigned": assigned}


@router.get("/projects/{slug}/export")
def export(ctx: Ctx = Depends(project_ctx)):
    """Passed annotations as JSONL, ready for training/delivery."""
    ctx.need("admin")
    rows = ctx.conn.execute(
        """SELECT i.external_id, s.data, s.worker_id, s.version, r.reviewer_id, s.definition_hash
           FROM tasks t JOIN items i ON i.id=t.item_id
           JOIN submissions s ON s.task_id=t.id AND s.version=(SELECT MAX(version) FROM submissions WHERE task_id=t.id)
           JOIN reviews r ON r.submission_id=s.id
           WHERE t.project_id=? AND t.status='passed' ORDER BY i.id""",
        (ctx.project["id"],),
    ).fetchall()
    lines = [
        db.dumps({"item": r["external_id"], "annotation": db.loads(r["data"]), "worker": r["worker_id"],
                  "version": r["version"], "reviewer": r["reviewer_id"], "definition_hash": r["definition_hash"]})
        for r in rows
    ]
    return PlainTextResponse("\n".join(lines) + ("\n" if lines else ""), media_type="application/x-ndjson")


# ----------------------------------------------------------------- worker / reviewer queues
def _task_rows(ctx: Ctx, where: str, params: tuple) -> list[dict]:
    rows = ctx.conn.execute(
        f"""SELECT t.*, i.external_id, {VERSIONS},
              lr.comment last_comment, lr.decision last_decision, lr.reviewer_id last_reviewer
            FROM tasks t JOIN items i ON i.id=t.item_id {LATEST_REVIEW}
            WHERE t.project_id=? AND {where} ORDER BY t.updated_at DESC, t.id""",
        (ctx.project["id"], *params),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/projects/{slug}/my-tasks")
def my_tasks(ctx: Ctx = Depends(project_ctx)):
    ctx.need("worker")
    return _task_rows(ctx, "t.assignee=?", (ctx.user,))


@router.get("/projects/{slug}/review-queue")
def review_queue(ctx: Ctx = Depends(project_ctx)):
    """Only the submissions routed to this reviewer."""
    ctx.need("reviewer")
    return {
        "pending": _task_rows(ctx, "t.status='submitted' AND t.reviewer_id=?", (ctx.user,)),
        "done": _task_rows(
            ctx, "t.status IN ('passed','failed') AND EXISTS (SELECT 1 FROM reviews r WHERE r.task_id=t.id AND r.reviewer_id=?)", (ctx.user,)
        ),
    }


# ----------------------------------------------------------------- task detail & actions
@router.get("/tasks/{task_id}")
def get_task(tc=Depends(task_ctx)):
    ctx, t = tc
    item = ctx.conn.execute("SELECT * FROM items WHERE id=?", (t["item_id"],)).fetchone()
    subs = ctx.conn.execute("SELECT * FROM submissions WHERE task_id=? ORDER BY version", (t["id"],)).fetchall()
    reviews = {r["submission_id"]: r for r in ctx.conn.execute("SELECT * FROM reviews WHERE task_id=?", (t["id"],))}
    history = []
    for s in subs:
        r = reviews.get(s["id"])
        history.append(
            {
                "version": s["version"], "worker": s["worker_id"], "submitted_at": s["submitted_at"],
                "data": db.loads(s["data"]), "checks": db.loads(s["check_results"]), "definition_hash": s["definition_hash"],
                "review": None if r is None else {
                    "reviewer": r["reviewer_id"], "decision": r["decision"], "comment": r["comment"],
                    "checklist": db.loads(r["checklist"]), "at": r["created_at"],
                },
            }
        )
    return {
        "id": t["id"],
        "project": project_summary(ctx.project),
        "status": t["status"],
        "assignee": t["assignee"],
        "reviewer": t["reviewer_id"],
        "draft": db.loads(t["draft"]),
        "item": item_json(ctx.defn.slug, item),
        "history": history,
        "roles": sorted(ctx.roles),
    }


class AnnotationBody(BaseModel):
    data: dict[str, Any]


def _own_open_task(ctx: Ctx, t: sqlite3.Row) -> None:
    ctx.need("worker")
    if t["assignee"] != ctx.user:
        raise HTTPException(403, "this task is not assigned to you")
    if t["status"] not in ("assigned", "failed", "submitted"):
        raise HTTPException(409, f"task is {t['status']}; nothing to edit")


def _item_meta(ctx: Ctx, t: sqlite3.Row) -> dict:
    row = ctx.conn.execute("SELECT payload FROM items WHERE id=?", (t["item_id"],)).fetchone()
    return db.loads(row["payload"]).get("meta", {})


@router.put("/tasks/{task_id}/draft")
def save_draft(body: AnnotationBody, tc=Depends(task_ctx)):
    ctx, t = tc
    _own_open_task(ctx, t)
    ctx.conn.execute("UPDATE tasks SET draft=?, updated_at=? WHERE id=?", (db.dumps(body.data), db.now(), t["id"]))
    return {"ok": True}


@router.post("/tasks/{task_id}/validate")
def validate(body: AnnotationBody, tc=Depends(task_ctx)):
    """Dry run of submit-time validation, so workers see problems while they work."""
    ctx, t = tc
    errors, checks = validate_annotation(ctx, body.data, _item_meta(ctx, t))
    return {"schema_errors": errors, "checks": checks}


@router.post("/tasks/{task_id}/submit")
def submit(body: AnnotationBody, tc=Depends(task_ctx)):
    ctx, t = tc
    _own_open_task(ctx, t)
    ctx.need_active()
    errors, checks = validate_annotation(ctx, body.data, _item_meta(ctx, t))
    blocking = [c for c in checks if c["severity"] == "error" and not c["passed"]]
    if errors or blocking:
        raise HTTPException(422, {"schema_errors": errors, "checks": checks})
    new_status = lifecycle.advance(t["status"], "submit", ctx.roles)
    record = (db.dumps(body.data), db.dumps(checks), ctx.project["definition_hash"], db.now())
    with db.tx(ctx.conn):
        if t["status"] == "submitted":
            # Not reviewed yet: replace the pending submission (reviewed ones are never changed).
            pending = ctx.conn.execute(
                "SELECT s.id, s.version FROM submissions s LEFT JOIN reviews r ON r.submission_id=s.id"
                " WHERE s.task_id=? AND r.id IS NULL ORDER BY s.version DESC LIMIT 1", (t["id"],)).fetchone()
            if pending is None:
                raise HTTPException(409, "this submission has already been reviewed")
            version = pending["version"]
            ctx.conn.execute("UPDATE submissions SET data=?, check_results=?, definition_hash=?, submitted_at=? WHERE id=?",
                             (*record, pending["id"]))
        else:
            version = ctx.conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM submissions WHERE task_id=?", (t["id"],)).fetchone()[0]
            ctx.conn.execute(
                "INSERT INTO submissions(task_id,worker_id,version,data,check_results,definition_hash,submitted_at) VALUES (?,?,?,?,?,?,?)",
                (t["id"], ctx.user, version, *record),
            )
        ctx.conn.execute("UPDATE tasks SET status=?, draft=NULL, updated_at=? WHERE id=?", (new_status, db.now(), t["id"]))
    return {"status": new_status, "version": version, "checks": checks}


class ReviewBody(BaseModel):
    decision: Literal["pass", "fail"]
    comment: str = ""
    checklist: dict[str, bool] = {}


@router.post("/tasks/{task_id}/review")
def review(body: ReviewBody, tc=Depends(task_ctx)):
    ctx, t = tc
    rules = ctx.defn.review
    new_status = lifecycle.advance(t["status"], body.decision, ctx.roles)
    if t["reviewer_id"] != ctx.user:
        raise HTTPException(403, f"this task is routed to {t['reviewer_id']} for review")
    unticked = [c for c in rules.checklist if not body.checklist.get(c)]
    if body.decision == "pass" and rules.require_full_checklist_to_pass and unticked:
        raise HTTPException(422, f"can't pass with unticked checklist items: {unticked}")
    if body.decision == "fail" and rules.require_comment_on_fail and not body.comment.strip():
        raise HTTPException(422, "a failed review needs a comment for the worker")
    with db.tx(ctx.conn):
        sub = ctx.conn.execute("SELECT id FROM submissions WHERE task_id=? ORDER BY version DESC LIMIT 1", (t["id"],)).fetchone()
        ctx.conn.execute(
            "INSERT INTO reviews(task_id,submission_id,reviewer_id,decision,comment,checklist,created_at) VALUES (?,?,?,?,?,?,?)",
            (t["id"], sub["id"], ctx.user, body.decision, body.comment.strip(), db.dumps(body.checklist), db.now()),
        )
        ctx.conn.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (new_status, db.now(), t["id"]))
    return {"status": new_status}
