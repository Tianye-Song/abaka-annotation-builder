"""The task state machine, shared by every project.

    unassigned --assign--> assigned --submit--> submitted --pass--> passed
                              ^                     |
                              |                   fail
                              |                     v
                          (reassign)             failed --submit (rework)--> submitted

A failed task keeps its assignee, so rework always goes back to the same worker
along with the reviewer's comment. Until the reviewer decides, the worker may resubmit a
submitted task; that replaces the pending (unreviewed) submission instead of adding a version.
"""
from __future__ import annotations

from fastapi import HTTPException

# (current status, action) -> (new status, role allowed to do it)
TRANSITIONS: dict[tuple[str, str], tuple[str, str]] = {
    ("unassigned", "assign"): ("assigned", "admin"),
    ("assigned", "assign"): ("assigned", "admin"),  # reassign before any work is submitted
    ("assigned", "submit"): ("submitted", "worker"),
    ("failed", "submit"): ("submitted", "worker"),
    ("submitted", "submit"): ("submitted", "worker"),  # change it before the reviewer has decided
    ("submitted", "pass"): ("passed", "reviewer"),
    ("submitted", "fail"): ("failed", "reviewer"),
}


# Statuses where a task still occupies its worker (SQL `IN` list, used by several queries).
OPEN_SQL = "('assigned','failed','submitted')"


def advance(status: str, action: str, roles: set[str]) -> str:
    """Return the next status, or raise 409/403 if the move isn't allowed."""
    rule = TRANSITIONS.get((status, action))
    if rule is None:
        raise HTTPException(409, f"can't {action} a task that is {status}")
    new_status, role = rule
    if role not in roles:
        raise HTTPException(403, f"only a {role} can {action}")
    return new_status
