"""End-to-end lifecycle for every example project, through the HTTP API.

assign -> submit -> fail (with comment) -> rework by the same worker -> pass
"""
import os
import tempfile
from pathlib import Path

os.environ["ANNOTATE_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import registry  # noqa: E402
from app.main import app  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# A valid annotation for each project, keyed by slug.
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
PROJECTS = [ROOT / "projects" / s for s in ("speaker-turns", "street-objects", "code-correctness")] + [ROOT / "examples" / "llm-rubric"]


@pytest.fixture(scope="module")
def client():
    for p in PROJECTS:
        registry.create_project(p)
    return TestClient(app)


def as_(user):
    return {"X-User": user}


def members(client, slug):
    p = client.get(f"/api/projects/{slug}", headers=as_("dan")).json()  # dan is in every project
    return {role: [m["id"] for m in ms] for role, ms in p["members"].items()}


@pytest.mark.parametrize("slug", list(GOOD))
def test_full_lifecycle(client, slug):
    m = members(client, slug)
    admin, worker, reviewer = m["admin"][0], m["worker"][0], m["reviewer"][0]

    assert client.post(f"/api/projects/{slug}/tasks", json={}, headers=as_(admin)).json()["created"] > 0
    rows = client.get(f"/api/projects/{slug}/overview", headers=as_(admin)).json()["rows"]
    task_id = rows[0]["task_id"]
    r = client.post(f"/api/projects/{slug}/tasks/assign", json={"task_ids": [task_id], "worker": worker}, headers=as_(admin))
    assert r.status_code == 200, r.text

    # Workers can't touch other people's tasks; reviewers can't review before submission.
    other = next((w for w in m["worker"] if w != worker), None)
    if other:
        assert client.get(f"/api/tasks/{task_id}", headers=as_(other)).status_code == 403
    assert client.post(f"/api/tasks/{task_id}/review", json={"decision": "pass"}, headers=as_(reviewer)).status_code == 409

    # Empty submission is rejected by the derived schema.
    bad = client.post(f"/api/tasks/{task_id}/submit", json={"data": {}}, headers=as_(worker))
    assert bad.status_code == 422 and bad.json()["detail"]["schema_errors"]

    assert client.post(f"/api/tasks/{task_id}/submit", json={"data": GOOD[slug]}, headers=as_(worker)).status_code == 200

    # Fail needs a comment; then the task goes back to the same worker.
    assert client.post(f"/api/tasks/{task_id}/review", json={"decision": "fail"}, headers=as_(reviewer)).status_code == 422
    r = client.post(f"/api/tasks/{task_id}/review", json={"decision": "fail", "comment": "tighten it up"}, headers=as_(reviewer))
    assert r.json()["status"] == "failed"
    mine = client.get(f"/api/projects/{slug}/my-tasks", headers=as_(worker)).json()
    assert any(t["id"] == task_id and t["status"] == "failed" and t["last_comment"] == "tighten it up" for t in mine)

    # Rework -> v2 -> pass (checklist must be fully ticked).
    assert client.post(f"/api/tasks/{task_id}/submit", json={"data": GOOD[slug]}, headers=as_(worker)).json()["version"] == 2
    checklist = client.get(f"/api/projects/{slug}", headers=as_(reviewer)).json()["definition"]["review"]["checklist"]
    if checklist:
        assert client.post(f"/api/tasks/{task_id}/review", json={"decision": "pass"}, headers=as_(reviewer)).status_code == 422
    r = client.post(f"/api/tasks/{task_id}/review", json={"decision": "pass", "checklist": {c: True for c in checklist}}, headers=as_(reviewer))
    assert r.json()["status"] == "passed"

    o = client.get(f"/api/projects/{slug}/overview", headers=as_(admin)).json()
    assert o["status_counts"]["passed"] == 1 and o["pass_rate"] == 0.5 and o["first_pass_rate"] == 0.0
    export = client.get(f"/api/projects/{slug}/export", headers=as_(admin)).text.strip().splitlines()
    assert len(export) == 1


def test_quality_checks_block_submit(client):
    slug = "speaker-turns"
    client.post(f"/api/projects/{slug}/tasks", json={}, headers=as_("alice"))
    rows = client.get(f"/api/projects/{slug}/overview", headers=as_("alice")).json()["rows"]
    tid = next(r["task_id"] for r in rows if r["status"] == "unassigned")
    client.post(f"/api/projects/{slug}/tasks/assign", json={"task_ids": [tid], "worker": "bob"}, headers=as_("alice"))
    overlapping = {
        "audio_quality": "clean",
        "segments": [
            {"start": 0, "end": 3, "speaker": "A", "text": "x"},
            {"start": 2, "end": 99, "speaker": "B", "text": "y"},
        ],
    }
    r = client.post(f"/api/tasks/{tid}/submit", json={"data": overlapping}, headers=as_("bob"))
    assert r.status_code == 422
    failed = {c["check"] for c in r.json()["detail"]["checks"] if not c["passed"]}
    assert {"no_overlap", "within_duration"} <= failed


def test_conditional_required_field(client):
    from app.api import Draft202012Validator
    from app.definition import load_definition, output_schema

    v = Draft202012Validator(output_schema(load_definition(ROOT / "projects" / "code-correctness")))
    assert list(v.iter_errors({"verdict": "correct", "reason": "fine"})) == []
    assert list(v.iter_errors({"verdict": "buggy", "reason": "broken"}))  # bug_category now required


def test_bad_definition_is_rejected(tmp_path):
    from pydantic import ValidationError
    from app.definition import ProjectDef

    with pytest.raises(ValidationError, match="does not work with modality"):
        ProjectDef.model_validate({
            "slug": "x", "name": "x", "modality": "text", "data": {"kind": "jsonl", "path": "a"},
            "task": {"fields": [{"id": "b", "type": "bbox", "classes": ["car"]}]},
        })
