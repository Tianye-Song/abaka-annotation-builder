// Widget registry: one entry per field type in backend/app/fields.py.
// The task page renders whatever fields the definition lists by looking them up here.
import type { FC } from "react";
import type { FieldDef, Item } from "../api";
import { AudioSegmentsField } from "./AudioSegmentsField";
import { BBoxField } from "./BBoxField";
import { ChoiceField, RatingField, TextField } from "./basic";

export interface WidgetProps {
  field: FieldDef;
  value: any;
  onChange: (v: any) => void;
  item: Item;
  readOnly: boolean;
}

export interface Widget {
  component: FC<WidgetProps>;
  /** Surface widgets render the item media themselves (you draw on the image, mark time on the audio). */
  surface?: boolean;
}

export const WIDGETS: Record<string, Widget> = {
  choice: { component: ChoiceField },
  text: { component: TextField },
  rating: { component: RatingField },
  bbox: { component: BBoxField, surface: true },
  audio_segments: { component: AudioSegmentsField, surface: true },
};

export function isRequired(field: FieldDef, values: Record<string, any>): boolean {
  if (field.required) return true;
  const w = field.required_when;
  return !!w && values[w.field] === w.equals;
}

/**
 * Apply one field change. A field that is only required when another field has a given value
 * (e.g. bug_category when verdict = buggy) is cleared when that value is changed away, so a
 * flipped answer can't leave a contradictory label behind.
 */
export function withChange(fields: FieldDef[], values: Record<string, any>, id: string, v: any): Record<string, any> {
  const next = { ...values, [id]: v };
  for (const f of fields) {
    const w = f.required_when;
    if (w && w.field === id && values[id] === w.equals && v !== w.equals) delete next[f.id];
  }
  return next;
}

/** Drop untouched values so "not filled in" reads as missing, not as an empty string. */
export function clean(values: Record<string, any>): Record<string, any> {
  return Object.fromEntries(Object.entries(values).filter(([, v]) => v !== null && v !== undefined && v !== ""));
}
