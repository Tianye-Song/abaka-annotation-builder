"""Project definition: the only thing a new project has to write.

A definition is YAML (written in the admin UI, or a projects/<slug>/project.yaml
seed) validated against the models below. It holds only what is unique to the
project; who works on it is managed separately (project_members). From it the platform derives everything project-specific:
the item loader, the worker's controls, the output JSON Schema, automatic
checks and the reviewer's checklist.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, model_validator

from .checks import CHECKS
from .fields import FIELD_TYPES

Role = Literal["admin", "worker", "reviewer"]
Modality = Literal["audio", "image", "text", "code"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataSource(_Strict):
    """How items are loaded.

    files: every file matching `glob` under `path` is one item (audio/image).
           An optional `meta` JSONL file adds per-file metadata keyed by filename.
    jsonl: every line of `path` is one item; must contain an `id`.
    """

    kind: Literal["files", "jsonl"]
    path: str
    glob: str = "*"
    meta: str | None = None


class Panel(_Strict):
    """A piece of item metadata to show next to the media (or as the item, for text)."""

    key: str
    label: str | None = None
    format: Literal["text", "code", "markdown"] = "text"


class Condition(_Strict):
    field: str
    equals: Any


class FieldDef(BaseModel):
    """One control in the task interface. Type-specific keys sit alongside the common ones."""

    model_config = ConfigDict(extra="allow")
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: str
    label: str | None = None
    help: str | None = None
    required: bool = False
    required_when: Condition | None = None

    _params: Any = PrivateAttr(default=None)

    @property
    def params(self) -> Any:
        return self._params

    @model_validator(mode="after")
    def _parse_params(self):
        ft = FIELD_TYPES.get(self.type)
        if ft is None:
            raise ValueError(f"field '{self.id}': unknown type '{self.type}' (known: {', '.join(FIELD_TYPES)})")
        self._params = ft.Params(**(self.model_extra or {}))
        return self


class CheckDef(BaseModel):
    model_config = ConfigDict(extra="allow")
    check: str
    severity: Literal["error", "warning"] = "error"
    _parsed: Any = PrivateAttr(default=None)

    @property
    def parsed(self) -> Any:
        return self._parsed

    @model_validator(mode="after")
    def _parse(self):
        if self.check not in CHECKS:
            raise ValueError(f"unknown check '{self.check}' (known: {', '.join(CHECKS)})")
        self._parsed = CHECKS[self.check][0](**(self.model_extra or {}))
        return self


class TaskDef(_Strict):
    instructions: str = ""
    fields: list[FieldDef] = Field(min_length=1)
    checks: list[CheckDef] = []


class ReviewRules(_Strict):
    """What the reviewer sees and how they decide."""

    checklist: list[str] = []
    require_full_checklist_to_pass: bool = True
    require_comment_on_fail: bool = True
    blocking_checks_auto_fail: bool = True  # error-level checks also block submit, so reviewers never see them


class ProjectDef(_Strict):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    description: str = ""
    modality: Modality
    data: DataSource
    display: list[Panel] = []
    task: TaskDef
    review: ReviewRules = ReviewRules()

    @model_validator(mode="after")
    def _cross_validate(self):
        ids = [f.id for f in self.task.fields]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate field ids: {sorted(dupes)}")
        by_id = {f.id: f for f in self.task.fields}
        for f in self.task.fields:
            ft = FIELD_TYPES[f.type]
            if self.modality not in ft.modalities:
                raise ValueError(f"field '{f.id}': type '{f.type}' does not work with modality '{self.modality}'")
            if f.required_when and f.required_when.field not in by_id:
                raise ValueError(f"field '{f.id}': required_when refers to unknown field '{f.required_when.field}'")
        for c in self.task.checks:
            fld = by_id.get(c.parsed.field)
            if fld is None:
                raise ValueError(f"check '{c.check}': unknown field '{c.parsed.field}'")
            allowed = CHECKS[c.check][2]
            if allowed and fld.type not in allowed:
                raise ValueError(f"check '{c.check}' can't run on field '{fld.id}' of type '{fld.type}'")
        return self


def output_schema(p: ProjectDef) -> dict:
    """Derive the JSON Schema every saved annotation for this project must match."""
    props, required, conditionals = {}, [], []
    for f in p.task.fields:
        ft = FIELD_TYPES[f.type]
        schema = {**ft.schema(f.params)}
        if f.label:
            schema["title"] = f.label
        if f.required:
            required.append(f.id)
            schema.update(ft.nonempty(f.params))
        props[f.id] = schema
        if f.required_when:
            w = f.required_when
            conditionals.append(
                {
                    "if": {"properties": {w.field: {"const": w.equals}}, "required": [w.field]},
                    "then": {"required": [f.id], "properties": {f.id: ft.nonempty(f.params)}},
                }
            )
    out: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"{p.name} annotation",
        "type": "object",
        "additionalProperties": False,
        "properties": props,
        "required": required,
    }
    if conditionals:
        out["allOf"] = conditionals
    return out


class DefinitionError(ValueError):
    """A definition that can't be used, with one message per problem (shown in the UI)."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def parse_definition(text: str) -> ProjectDef:
    """YAML text -> validated definition, or DefinitionError listing every problem."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise DefinitionError([f"YAML syntax: {e}"]) from None
    if not isinstance(raw, dict):
        raise DefinitionError(["the definition must be a YAML mapping (key: value pairs)"])
    try:
        return ProjectDef.model_validate(raw)
    except ValidationError as e:
        raise DefinitionError(
            [f"{'.'.join(str(x) for x in err['loc']) or 'definition'}: {err['msg'].removeprefix('Value error, ')}" for err in e.errors()]
        ) from None


def definition_hash(p: ProjectDef) -> str:
    blob = json.dumps(p.model_dump(mode="json"), sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:12]

