"""Field-type registry: the building blocks a project definition composes.

Each field type knows three things:
  * which parameters it accepts in a project definition (`Params`),
  * which modalities it can be used with,
  * the JSON Schema fragment its saved value must match.

The frontend has a matching widget registry (frontend/src/fields). Adding a new
kind of control (e.g. polygon, keypoints) means adding one entry here and one
widget there; every project can then use it from YAML alone.
"""
from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


NOT_BLANK = r"\S"  # at least one non-whitespace character


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldType:
    name: ClassVar[str]
    Params: ClassVar[type[_Params]] = _Params
    modalities: ClassVar[set[str]] = {"audio", "image", "text"}

    def schema(self, p: Any) -> dict:
        raise NotImplementedError

    def nonempty(self, p: Any) -> dict:
        """Extra constraint applied when the field is required ("present and not empty")."""
        return {}


# ---------------------------------------------------------------- generic fields
class ChoiceParams(_Params):
    choices: list[str] = Field(min_length=1)
    multiple: bool = False


class Choice(FieldType):
    name = "choice"
    Params = ChoiceParams

    def schema(self, p: ChoiceParams) -> dict:
        one = {"type": "string", "enum": p.choices}
        return {"type": "array", "items": one, "uniqueItems": True} if p.multiple else one

    def nonempty(self, p: ChoiceParams) -> dict:
        return {"minItems": 1} if p.multiple else {}


class TextParams(_Params):
    multiline: bool = False
    placeholder: str = ""


class Text(FieldType):
    name = "text"
    Params = TextParams

    def schema(self, p: TextParams) -> dict:
        return {"type": "string"}

    def nonempty(self, p: TextParams) -> dict:
        return {"pattern": NOT_BLANK}


class RatingParams(_Params):
    min: int = 1
    max: int = 5
    labels: dict[int, str] = {}

    @model_validator(mode="after")
    def _range(self):
        if self.min >= self.max:
            raise ValueError("rating: min must be < max")
        return self


class Rating(FieldType):
    name = "rating"
    Params = RatingParams

    def schema(self, p: RatingParams) -> dict:
        return {"type": "integer", "minimum": p.min, "maximum": p.max}


# ------------------------------------------------------- modality-bound fields
class BBoxParams(_Params):
    classes: list[str] = Field(min_length=1)


class BBox(FieldType):
    """Bounding boxes drawn on the item image, in natural-image pixel coordinates."""

    name = "bbox"
    Params = BBoxParams
    modalities = {"image"}

    def schema(self, p: BBoxParams) -> dict:
        return {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["x", "y", "w", "h", "label"],
                "additionalProperties": False,
                "properties": {
                    "x": {"type": "number", "minimum": 0},
                    "y": {"type": "number", "minimum": 0},
                    "w": {"type": "number", "exclusiveMinimum": 0},
                    "h": {"type": "number", "exclusiveMinimum": 0},
                    "label": {"type": "string", "enum": p.classes},
                },
            },
        }

    def nonempty(self, p: BBoxParams) -> dict:
        return {"minItems": 1}


class SegmentsParams(_Params):
    speakers: list[str] = Field(min_length=1)
    transcribe: bool = True


class AudioSegments(FieldType):
    """Time ranges on the audio clip, each with a speaker and (optionally) a transcript."""

    name = "audio_segments"
    Params = SegmentsParams
    modalities = {"audio"}

    def schema(self, p: SegmentsParams) -> dict:
        props: dict[str, Any] = {
            "start": {"type": "number", "minimum": 0},
            "end": {"type": "number", "minimum": 0},
            "speaker": {"type": "string", "enum": p.speakers},
        }
        required = ["start", "end", "speaker"]
        if p.transcribe:
            props["text"] = {"type": "string", "pattern": NOT_BLANK}
            required.append("text")
        return {
            "type": "array",
            "items": {"type": "object", "required": required, "additionalProperties": False, "properties": props},
        }

    def nonempty(self, p: SegmentsParams) -> dict:
        return {"minItems": 1}


FIELD_TYPES: dict[str, FieldType] = {t.name: t() for t in (Choice, Text, Rating, BBox, AudioSegments)}
