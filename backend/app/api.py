"""HTTP API shared by every project. Nothing here knows about audio, images or code:
project-specific behaviour comes from the definition (schema, checks, review rules).
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import PlainTextResponse
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from . import db, lifecycle, registry
from .checks import run_checks
from .definition import ProjectDef, output_schema
from .fields import NOT_BLANK

router = APIRouter(prefix="/api")


# ----------------------------------------------------------------- dependencies
def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def get_user(x_user: str = Header(..., description="Mock auth: the logged-in user id"), conn=Depends(get_conn)) -> str:
    if conn.execute("SELECT 1 FROM users WHERE id=?", (x_user,)).fetchone() is None:
        raise HTTPException(401, "unknown user")
    return x_user


@dataclass
class Ctx:
    conn: sqlite3.Connection
    user: str
    project: sqlite3.Row
    defn: ProjectDef
    roles: set[str]

    def need(self, role: str) -> None:
        if role not in self.roles:
            raise HTTPException(403, f"you are not a {role} on {self.defn.slug}")


def load_ctx(conn: sqlite3.Connection, user: str, slug: str) -> Ctx:
    found = registry.get_definition(conn, slug)
    if found is None:
        raise HTTPException(404, f"no project '{slug}'")
    row, defn = found
    roles = {
        r["role"]
        for r in conn.execute("SELECT role FROM memberships WHERE project_id=? AND user_id=?", (row["id"], user))
    }
    if not roles:
        raise HTTPException(403, "you are not a member of this project")
    return Ctx(conn, user, row, defn, roles)


def project_ctx(slug: str, user: str = Depends(get_user), conn=Depends(get_conn)) -> Ctx:
    return load_ctx(conn, user, slug)


def task_ctx(task_id: int, user: str = Depends(get_user), conn=Depends(get_conn)) -> tuple[Ctx, sqlite3.Row]:
    task = conn.execute(
        "SELECT t.*, p.slug FROM tasks t JOIN projects p ON p.id=t.project_id WHERE t.id=?", (task_id,)
    ).fetchone()
    if task is None:
        raise HTTPException(404, "no such task")
    ctx = load_ctx(conn, user, task["slug"])
    # Workers only see their own tasks; admins and reviewers see all tasks in the project.
    if not ctx.roles & {"admin", "reviewer"} and task["assignee"] != user:
        raise HTTPException(403, "this task is not assigned to you")
    return ctx, task


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
    return {
        "id": row["id"],
        "external_id": row["external_id"],
        "media_url": media_url(slug, payload.get("media")),
        "meta": payload.get("meta", {}),
    }


def project_summary(row: sqlite3.Row) -> dict:
    return {"slug": row["slug"], "name": row["name"], "modality": row["modality"]}


# ----------------------------------------------------------------- users / portal
@router.get("/users")
def list_users(conn=Depends(get_conn)):
    """Login picker: every user and their role in each project."""
    users = {r["id"]: {"id": r["id"], "name": r["name"], "projects": []} for r in conn.execute("SELECT * FROM users ORDER BY id")}
    for m in conn.execute(
        "SELECT m.user_id, m.role, p.slug, p.name FROM memberships m JOIN projects p ON p.id=m.project_id ORDER BY p.slug"
    ):
        users[m["user_id"]]["projects"].append({"slug": m["slug"], "name": m["name"], "role": m["role"]})
    return list(users.values())


@router.get("/me/projects")
def my_projects(user: str = Depends(get_user), conn=Depends(get_conn)):
    """Unified portal: every project the user can access, their roles, and what's waiting for them."""
    rows = conn.execute(
        "SELECT p.*, group_concat(m.role) AS roles FROM projects p JOIN memberships m ON m.project_id=p.id"
        " WHERE m.user_id=? GROUP BY p.id ORDER BY p.name",
        (user,),
    ).fetchall()
    out = []
    for p in rows:
        counts = conn.execute(
            """SELECT
                 COALESCE(SUM(status='assigned' AND assignee=:u),0) AS todo,
                 COALESCE(SUM(status='failed'   AND assignee=:u),0) AS rework,
                 COALESCE(SUM(status='submitted'),0)               AS to_review,
                 COALESCE(SUM(status='unassigned'),0)              AS unassigned,
                 COALESCE(SUM(status='passed'),0)                  AS passed,
                 COUNT(*)                              AS tasks
               FROM tasks WHERE project_id=:p""",
            {"u": user, "p": p["id"]},
        ).fetchone()
        out.append({**project_summary(p), "roles": sorted(p["roles"].split(",")), "counts": dict(counts)})
    return out


# ----------------------------------------------------------------- project
@router.get("/projects/{slug}")
def get_project(ctx: Ctx = Depends(project_ctx)):
    members = defaultdict(list)
    for m in ctx.conn.execute(
        "SELECT m.user_id, u.name, m.role FROM memberships m JOIN users u ON u.id=m.user_id WHERE project_id=?",
        (ctx.project["id"],),
    ):
        members[m["role"]].append({"id": m["user_id"], "name": m["name"]})
    return {
        **project_summary(ctx.project),
        "description": ctx.defn.description,
        "definition": ctx.defn.model_dump(mode="json", exclude={"members"}),
        "definition_hash": ctx.project["definition_hash"],
        "output_schema": output_schema(ctx.defn),
        "roles": sorted(ctx.roles),
        "members": members,
    }


@router.get("/projects/{slug}/definition.yaml", response_class=PlainTextResponse)
def get_definition_source(ctx: Ctx = Depends(project_ctx)):
    path = registry.Path(ctx.project["source_dir"]) / "project.yaml"
    return path.read_text()


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
        """SELECT u.id, u.name,
             (SELECT COUNT(*) FROM tasks t WHERE t.project_id=:p AND t.assignee=u.id) assigned,
             (SELECT COUNT(*) FROM tasks t WHERE t.project_id=:p AND t.assignee=u.id AND t.status='passed') passed,
             (SELECT COUNT(*) FROM tasks t WHERE t.project_id=:p AND t.assignee=u.id AND t.status IN ('assigned','failed')) open,
             (SELECT COUNT(*) FROM reviews r JOIN tasks t ON t.id=r.task_id WHERE t.project_id=:p AND t.assignee=u.id) reviews,
             (SELECT COUNT(*) FROM reviews r JOIN tasks t ON t.id=r.task_id WHERE t.project_id=:p AND t.assignee=u.id AND r.decision='pass') review_passes
           FROM memberships m JOIN users u ON u.id=m.user_id
           WHERE m.project_id=:p AND m.role='worker' ORDER BY u.id""",
        {"p": pid},
    ).fetchall()
    rows = c.execute(
        """SELECT i.*, t.id task_id, t.status, t.assignee, t.updated_at,
             (SELECT COUNT(*) FROM submissions s WHERE s.task_id=t.id) versions,
             (SELECT r.decision FROM reviews r WHERE r.task_id=t.id ORDER BY r.id DESC LIMIT 1) last_decision
           FROM items i LEFT JOIN tasks t ON t.item_id=i.id WHERE i.project_id=? ORDER BY i.id""",
        (pid,),
    ).fetchall()
    rate = lambda a, b: (a / b) if b else None  # noqa: E731
    return {
        "items": n_items,
        "status_counts": {s: by_status.get(s, 0) for s in ("unassigned", "assigned", "submitted", "failed", "passed")},
        "no_task": n_items - sum(by_status.values()),
        "reviews": rv["n"],
        "pass_rate": rate(rv["passes"] or 0, rv["n"]),
        "first_pass_rate": rate(rv["first_passes"] or 0, rv["first_n"] or 0),
        "workers": [{**dict(w), "pass_rate": rate(w["review_passes"], w["reviews"])} for w in workers],
        "rows": [
            {
                "item": item_json(ctx.defn.slug, r),
                "task_id": r["task_id"],
                "status": r["status"],
                "assignee": r["assignee"],
                "versions": r["versions"],
                "last_decision": r["last_decision"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ],
    }


@router.post("/projects/{slug}/items/load")
def load_items(ctx: Ctx = Depends(project_ctx)):
    """Re-scan the project's data source and add any new items."""
    ctx.need("admin")
    with db.tx(ctx.conn):
        added = registry.import_items(ctx.conn, ctx.project["id"], ctx.defn, registry.Path(ctx.project["source_dir"]))
    return {"added": added}


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
    worker: str | None = None  # None = spread across workers, least-loaded first


@router.post("/projects/{slug}/tasks/assign")
def assign_tasks(body: Assign, ctx: Ctx = Depends(project_ctx)):
    ctx.need("admin")
    pid = ctx.project["id"]
    workers = [r["user_id"] for r in ctx.conn.execute("SELECT user_id FROM memberships WHERE project_id=? AND role='worker' ORDER BY user_id", (pid,))]
    if not workers:
        raise HTTPException(400, "this project has no workers")
    if body.worker is not None and body.worker not in workers:
        raise HTTPException(400, f"{body.worker} is not a worker on this project")
    load = {w: 0 for w in workers}
    for r in ctx.conn.execute(
        "SELECT assignee, COUNT(*) n FROM tasks WHERE project_id=? AND status IN ('assigned','failed','submitted') AND assignee IS NOT NULL GROUP BY assignee",
        (pid,),
    ):
        if r["assignee"] in load:
            load[r["assignee"]] = r["n"]
    assigned = []
    with db.tx(ctx.conn):
        for tid in body.task_ids:
            t = ctx.conn.execute("SELECT * FROM tasks WHERE id=? AND project_id=?", (tid, pid)).fetchone()
            if t is None:
                raise HTTPException(404, f"no task {tid} in this project")
            new_status = lifecycle.advance(t["status"], "assign", ctx.roles)
            who = body.worker or min(load, key=lambda w: (load[w], w))
            load[who] += 1
            ctx.conn.execute(
                "UPDATE tasks SET status=?, assignee=?, updated_at=? WHERE id=?", (new_status, who, db.now(), tid)
            )
            assigned.append({"task_id": tid, "worker": who})
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
        f"""SELECT t.*, i.external_id,
              (SELECT COUNT(*) FROM submissions s WHERE s.task_id=t.id) versions,
              (SELECT r.comment FROM reviews r WHERE r.task_id=t.id ORDER BY r.id DESC LIMIT 1) last_comment,
              (SELECT r.decision FROM reviews r WHERE r.task_id=t.id ORDER BY r.id DESC LIMIT 1) last_decision,
              (SELECT r.reviewer_id FROM reviews r WHERE r.task_id=t.id ORDER BY r.id DESC LIMIT 1) last_reviewer
            FROM tasks t JOIN items i ON i.id=t.item_id
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
    ctx.need("reviewer")
    return {
        "pending": _task_rows(ctx, "t.status='submitted'", ()),
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
                "version": s["version"],
                "worker": s["worker_id"],
                "submitted_at": s["submitted_at"],
                "data": db.loads(s["data"]),
                "checks": db.loads(s["check_results"]),
                "definition_hash": s["definition_hash"],
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
    if t["status"] not in ("assigned", "failed"):
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
    errors, checks = validate_annotation(ctx, body.data, _item_meta(ctx, t))
    blocking = [c for c in checks if c["severity"] == "error" and not c["passed"]]
    if errors or blocking:
        raise HTTPException(422, {"schema_errors": errors, "checks": checks})
    new_status = lifecycle.advance(t["status"], "submit", ctx.roles)
    with db.tx(ctx.conn):
        version = ctx.conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM submissions WHERE task_id=?", (t["id"],)).fetchone()[0]
        ctx.conn.execute(
            "INSERT INTO submissions(task_id,worker_id,version,data,check_results,definition_hash,submitted_at) VALUES (?,?,?,?,?,?,?)",
            (t["id"], ctx.user, version, db.dumps(body.data), db.dumps(checks), ctx.project["definition_hash"], db.now()),
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
    if t["assignee"] == ctx.user:
        raise HTTPException(403, "you can't review your own work")
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
