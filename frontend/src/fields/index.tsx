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

/** Drop untouched values so "not filled in" reads as missing, not as an empty string. */
export function clean(values: Record<string, any>): Record<string, any> {
  return Object.fromEntries(Object.entries(values).filter(([, v]) => v !== null && v !== undefined && v !== ""));
}
