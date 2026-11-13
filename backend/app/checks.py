"""Automatic quality checks a project can switch on from its definition.

A check runs on every submission (and on demand while the worker is still
editing). Checks with severity "error" block submission; "warning" results are
shown to the reviewer as signals but don't block anything.

Each check is a function (annotation, item_meta, params) -> list of problems.
An empty list means the check passed.
"""
from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, ConfigDict


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str


class MinCount(_P):
    min: int = 1


class MinWords(_P):
    min: int = 1


class MinBoxSize(_P):
    min_px: float = 4


class Coverage(_P):
    min_ratio: float = 0.5


class FieldOnly(_P):
    pass


Check = Callable[[dict, dict, Any], list[str]]


def _min_count(ann: dict, meta: dict, p: MinCount) -> list[str]:
    n = len(ann.get(p.field) or [])
    return [] if n >= p.min else [f"{p.field}: has {n}, needs at least {p.min}"]


def _min_words(ann: dict, meta: dict, p: MinWords) -> list[str]:
    value = ann.get(p.field)
    if not value:  # empty optional field: nothing to check
        return []
    n = len(str(value).split())
    return [] if n >= p.min else [f"{p.field}: {n} words, needs at least {p.min}"]


def _no_overlap(ann: dict, meta: dict, p: FieldOnly) -> list[str]:
    segs = sorted(ann.get(p.field) or [], key=lambda s: s["start"])
    out = []
    for s in segs:
        if s["end"] <= s["start"]:
            out.append(f"segment {s['start']:.2f}s ends before it starts")
    for a, b in zip(segs, segs[1:]):
        if b["start"] < a["end"] - 0.01:
            out.append(f"segments overlap at {b['start']:.2f}s–{a['end']:.2f}s")
    return out


def _within_duration(ann: dict, meta: dict, p: FieldOnly) -> list[str]:
    dur = meta.get("duration")
    if dur is None:
        return []
    return [
        f"segment {s['start']:.2f}–{s['end']:.2f}s runs past the clip end ({dur:.2f}s)"
        for s in ann.get(p.field) or []
        if s["end"] > dur + 0.05
    ]


def _coverage(ann: dict, meta: dict, p: Coverage) -> list[str]:
    dur = meta.get("duration")
    if not dur:
        return []
    covered = sum(max(0.0, s["end"] - s["start"]) for s in ann.get(p.field) or [])
    ratio = covered / dur
    return [] if ratio >= p.min_ratio else [f"segments cover {ratio:.0%} of the clip (expected ≥ {p.min_ratio:.0%})"]


def _within_image(ann: dict, meta: dict, p: FieldOnly) -> list[str]:
    w, h = meta.get("width"), meta.get("height")
    if not (w and h):
        return []
    return [
        f"box #{i + 1} ({b['label']}) extends outside the image"
        for i, b in enumerate(ann.get(p.field) or [])
        if b["x"] + b["w"] > w + 1 or b["y"] + b["h"] > h + 1
    ]


def _min_box_size(ann: dict, meta: dict, p: MinBoxSize) -> list[str]:
    return [
        f"box #{i + 1} ({b['label']}) is smaller than {p.min_px}px"
        for i, b in enumerate(ann.get(p.field) or [])
        if b["w"] < p.min_px or b["h"] < p.min_px
    ]


# name -> (params model, function, field types it applies to or None for any)
CHECKS: dict[str, tuple[type[_P], Check, set[str] | None]] = {
    "min_count": (MinCount, _min_count, {"bbox", "audio_segments", "choice"}),
    "min_words": (MinWords, _min_words, {"text"}),
    "no_overlap": (FieldOnly, _no_overlap, {"audio_segments"}),
    "within_duration": (FieldOnly, _within_duration, {"audio_segments"}),
    "coverage": (Coverage, _coverage, {"audio_segments"}),
    "within_image": (FieldOnly, _within_image, {"bbox"}),
    "min_box_size": (MinBoxSize, _min_box_size, {"bbox"}),
}


def run_checks(project, annotation: dict, item_meta: dict) -> list[dict]:
    """Run every configured check. Returns one result row per check."""
    results = []
    for c in project.task.checks:
        _, fn, _ = CHECKS[c.check]
        problems = fn(annotation, item_meta, c.parsed)
        results.append(
            {
                "check": c.check,
                "field": c.parsed.field,
                "severity": c.severity,
                "passed": not problems,
                "messages": problems,
            }
        )
    return results
