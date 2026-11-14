"""End-to-end through the HTTP API: exactly the calls the UI makes.

  admin creates a project (definition + uploaded data) -> staffs it (worker + reviewer)
  -> creates and assigns tasks -> worker submits -> routed reviewer fails it
  -> same worker reworks -> reviewer passes -> admin sees progress and exports.
"""
import os
import tempfile
from pathlib import Path

os.environ["ANNOTATE_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")

import pytest  # noqa: E402
import yaml  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

GOOD = {
    "speaker-turns": {
        "segments": [
            {"start": 0.4, "end": 2.0, "speaker": "A", "text": "Hi, is this the front desk?"},
            {"start": 2.5, "end": 4.6, "speaker": "B", "text": "Yes it is. How can I help you today?"},
        ],
        "audio_quality": "clean",
    },
    "street-objects": {"boxes": [{"x": 10, "y": 280, "w": 120, "h": 60, "label": "car"}]},
    "code-correctness": {"verdict": "buggy", "bug_category": "edge-case", "reason": "Fails for negative numbers: max_of([-3, -1]) returns 0."},
    "llm-rubric": {"accuracy": 2, "helpfulness": 2, "tone": 4, "justification": "Wrong author, it was Jane Austen."},
}


PASSWORDS = {u["id"]: u["password"] for u in yaml.safe_load((ROOT / "config/seed.yaml").read_text())["users"]}
PASSWORDS["frank"] = "frank-pass"
_tokens: dict[str, str] = {}
_client: TestClient | None = None


def as_(user):
    """Auth header for a user, logging in through /api/login the first time."""
    if user not in _tokens:
        r = _client.post("/api/login", json={"user_id": user, "password": PASSWORDS[user]})
        assert r.status_code == 200, r.text
        _tokens[user] = r.json()["token"]
    return {"Authorization": f"Bearer {_tokens[user]}"}


@pytest.fixture(scope="module")
def client():
    global _client
    with TestClient(app) as c:  # runs startup: schema + first-run seed
        _client = c
        yield c


def test_login_requires_the_right_password(client):
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/login", json={"user_id": "alice", "password": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"user_id": "nobody", "password": "x"}).status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer forged"}).status_code == 401
    assert client.get("/api/me", headers=as_("bob")).json()["roles"] == ["worker"]
    assert [a["id"] for a in client.get("/api/accounts").json()] == ["alice", "bob", "carol"]


def test_seeded_three_accounts(client):
    users = {u["id"]: u["roles"] for u in client.get("/api/users", headers=as_("alice")).json()}
    assert users == {"alice": ["admin"], "bob": ["worker"], "carol": ["reviewer"]}
    for user, role in (("alice", "admin"), ("bob", "worker"), ("carol", "reviewer")):
        projects = client.get("/api/me/projects", headers=as_(user)).json()
        assert len(projects) == 3 and all(p["roles"] == [role] for p in projects)


def test_admin_creates_fourth_project_in_ui(client):
    yaml_text = (ROOT / "examples/llm-rubric/project.yaml").read_text()
    data = (ROOT / "examples/llm-rubric/items.jsonl").read_bytes()

    # Non-admins can't create projects.
    r = client.post("/api/projects", data={"definition": yaml_text}, headers=as_("bob"))
    assert r.status_code == 403

    # Dry-run validation shows what will be generated.
    v = client.post("/api/projects/validate", json={"yaml": yaml_text}, headers=as_("alice")).json()
    assert v["ok"] and [f["type"] for f in v["derived"]["fields"]] == ["rating", "rating", "rating", "choice", "text"]

    r = client.post("/api/projects", data={"definition": yaml_text},
                    files=[("files", ("items.jsonl", data, "application/x-ndjson"))], headers=as_("alice"))
    assert r.status_code == 200, r.text
    assert r.json()["items_added"] == 5
    assert client.post("/api/projects", data={"definition": yaml_text}, headers=as_("alice")).status_code == 409

    for uid, role in (("bob", "worker"), ("carol", "reviewer")):
        r = client.post("/api/projects/llm-rubric/members", json={"user_id": uid, "role": role}, headers=as_("alice"))
        assert r.status_code == 200, r.text


def test_bad_definition_lists_problems(client):
    bad = "slug: x\nname: X\nmodality: text\ndata: {kind: jsonl, path: a.jsonl}\ntask:\n  fields:\n    - {id: b, type: bbox, classes: [car]}\n"
    v = client.post("/api/projects/validate", json={"yaml": bad}, headers=as_("alice")).json()
    assert not v["ok"] and any("does not work with modality" in p for p in v["problems"])
    assert client.post("/api/projects", data={"definition": bad}, headers=as_("alice")).status_code == 422


@pytest.mark.parametrize("slug", list(GOOD))
def test_full_lifecycle(client, slug):
    p = client.get(f"/api/projects/{slug}", headers=as_("alice")).json()
    worker, reviewer = p["members"]["worker"][0]["id"], p["members"]["reviewer"][0]["id"]

    assert client.post(f"/api/projects/{slug}/tasks", json={}, headers=as_("alice")).json()["created"] > 0
    rows = client.get(f"/api/projects/{slug}/overview", headers=as_("alice")).json()["rows"]
    task_id = rows[0]["task_id"]
    r = client.post(f"/api/projects/{slug}/tasks/assign", json={"task_ids": [task_id], "worker": worker}, headers=as_("alice"))
    assert r.json()["assigned"][0]["reviewer"] == reviewer  # auto-picked from the team's reviewers

    bad = client.post(f"/api/tasks/{task_id}/submit", json={"data": {}}, headers=as_(worker))
    assert bad.status_code == 422 and bad.json()["detail"]["schema_errors"]
    assert client.post(f"/api/tasks/{task_id}/submit", json={"data": GOOD[slug]}, headers=as_(worker)).status_code == 200

    # Only the routed reviewer sees and decides it.
    assert any(t["id"] == task_id for t in client.get(f"/api/projects/{slug}/review-queue", headers=as_(reviewer)).json()["pending"])
    assert client.post(f"/api/tasks/{task_id}/review", json={"decision": "fail"}, headers=as_(reviewer)).status_code == 422
    r = client.post(f"/api/tasks/{task_id}/review", json={"decision": "fail", "comment": "tighten it up"}, headers=as_(reviewer))
    assert r.json()["status"] == "failed"
    mine = client.get(f"/api/projects/{slug}/my-tasks", headers=as_(worker)).json()
    assert any(t["id"] == task_id and t["status"] == "failed" and t["last_comment"] == "tighten it up" for t in mine)

    assert client.post(f"/api/tasks/{task_id}/submit", json={"data": GOOD[slug]}, headers=as_(worker)).json()["version"] == 2
    # v2 is unreviewed, so the queue must not show v1's fail as the "last review".
    mine = client.get(f"/api/projects/{slug}/my-tasks", headers=as_(worker)).json()
    row = next(t for t in mine if t["id"] == task_id)
    assert row["last_decision"] is None and row["last_comment"] is None
    checklist = p["definition"]["review"]["checklist"]
    r = client.post(f"/api/tasks/{task_id}/review", json={"decision": "pass", "checklist": {c: True for c in checklist}}, headers=as_(reviewer))
    assert r.json()["status"] == "passed"

    o = client.get(f"/api/projects/{slug}/overview", headers=as_("alice")).json()
    assert o["status_counts"]["passed"] == 1 and o["pass_rate"] == 0.5 and o["first_pass_rate"] == 0.0
    w = next(w for w in o["workers"] if w["id"] == worker)
    assert (w["assigned"], w["passed"], w["open"], w["reviews"], w["pass_rate"]) == (1, 1, 0, 2, 0.5)
    row = next(r for r in o["rows"] if r["task_id"] == task_id)
    assert row["versions"] == 2 and row["last_decision"] == "pass"
    assert len(client.get(f"/api/projects/{slug}/export", headers=as_("alice")).text.strip().splitlines()) == 1


def test_only_routed_reviewer_can_review(client):
    slug = "street-objects"
    rows = client.get(f"/api/projects/{slug}/overview", headers=as_("alice")).json()["rows"]
    tid = next(r["task_id"] for r in rows if r["status"] == "unassigned")
    client.post(f"/api/projects/{slug}/tasks/assign", json={"task_ids": [tid], "worker": "bob"}, headers=as_("alice"))
    client.post(f"/api/tasks/{tid}/submit", json={"data": GOOD[slug]}, headers=as_("bob"))
    # alice is an admin, not this task's reviewer (carol is)
    r = client.post(f"/api/tasks/{tid}/review", json={"decision": "fail", "comment": "x"}, headers=as_("alice"))
    assert r.status_code == 403


def test_quality_checks_block_submit(client):
    slug = "speaker-turns"
    rows = client.get(f"/api/projects/{slug}/overview", headers=as_("alice")).json()["rows"]
    tid = next(r["task_id"] for r in rows if r["status"] == "unassigned")
    client.post(f"/api/projects/{slug}/tasks/assign", json={"task_ids": [tid], "worker": "bob"}, headers=as_("alice"))
    overlapping = {"audio_quality": "clean", "segments": [
        {"start": 0, "end": 3, "speaker": "A", "text": "x"}, {"start": 2, "end": 99, "speaker": "B", "text": "y"}]}
    r = client.post(f"/api/tasks/{tid}/submit", json={"data": overlapping}, headers=as_("bob"))
    assert r.status_code == 422
    assert {"no_overlap", "within_duration"} <= {c["check"] for c in r.json()["detail"]["checks"] if not c["passed"]}


def test_upload_more_items_and_pause_project(client):
    slug = "code-correctness"
    line = b'{"id": "snippet-99", "intent": "Return 1.", "code": "def one():\\n    return 1"}\n'
    r = client.post(f"/api/projects/{slug}/items/upload", files=[("files", ("more.jsonl", line, "application/x-ndjson"))], headers=as_("alice"))
    assert r.json()["added"] == 1
    assert client.put(f"/api/projects/{slug}/status", json={"status": "paused"}, headers=as_("alice")).status_code == 200
    client.post(f"/api/projects/{slug}/tasks", json={}, headers=as_("alice"))
    rows = client.get(f"/api/projects/{slug}/overview", headers=as_("alice")).json()["rows"]
    tid = next(r["task_id"] for r in rows if r["status"] == "unassigned")
    assert client.post(f"/api/projects/{slug}/tasks/assign", json={"task_ids": [tid]}, headers=as_("alice")).status_code == 409
    client.put(f"/api/projects/{slug}/status", json={"status": "active"}, headers=as_("alice"))


def test_user_management(client):
    new = {"id": "frank", "name": "Frank", "roles": ["reviewer"], "password": "frank-pass"}
    assert client.post("/api/users", json=new, headers=as_("bob")).status_code == 403
    assert client.post("/api/users", json=new, headers=as_("alice")).status_code == 200
    assert any(u["id"] == "frank" and u["roles"] == ["reviewer"] for u in client.get("/api/users", headers=as_("alice")).json())
    assert client.get("/api/me", headers=as_("frank")).json()["id"] == "frank"
    # Admin resets frank's password: the old session is signed out, the new password works.
    old = as_("frank")
    assert client.patch("/api/users/frank", json={"password": "new-pass"}, headers=as_("alice")).status_code == 200
    assert client.get("/api/me", headers=old).status_code == 401
    assert client.post("/api/login", json={"user_id": "frank", "password": "new-pass"}).status_code == 200


def test_reuse_previous_project_definition_and_data(client):
    t = client.get("/api/templates", headers=as_("alice")).json()
    src = next(p for p in t["projects"] if p["slug"] == "street-objects")
    assert src["items"] == 7 and "bbox" in src["yaml"]
    yaml_text = src["yaml"].replace("slug: street-objects", "slug: street-objects-v2").replace("[car, person, tree]", "[car, person, tree, sun]")
    r = client.post("/api/projects", data={"definition": yaml_text, "copy_data_from": "street-objects"}, headers=as_("alice"))
    assert r.status_code == 200, r.text
    assert r.json()["items_added"] == 7  # same images, no upload
    p = client.get("/api/projects/street-objects-v2", headers=as_("alice")).json()
    assert p["definition"]["task"]["fields"][0]["classes"] == ["car", "person", "tree", "sun"]
    assert p["created_by"] == "alice" and not ({"worker", "reviewer"} & p["members"].keys())

