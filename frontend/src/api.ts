// Thin client for the shared API, plus the types the UI shares with it.
import { useCallback, useEffect, useState } from "react";

export type Role = "admin" | "worker" | "reviewer";
export type Status = "unassigned" | "assigned" | "submitted" | "failed" | "passed";

export interface FieldDef {
  id: string;
  type: string;
  label?: string | null;
  help?: string | null;
  required: boolean;
  required_when?: { field: string; equals: unknown } | null;
  [param: string]: any; // type-specific params (choices, classes, speakers, ...)
}

export interface Panel { key: string; label?: string | null; format: "text" | "code" | "markdown" }

export interface Definition {
  slug: string;
  name: string;
  modality: "audio" | "image" | "text";
  description: string;
  display: Panel[];
  task: { instructions: string; fields: FieldDef[]; checks: { check: string; severity: string; field: string }[] };
  review: { checklist: string[]; require_full_checklist_to_pass: boolean; require_comment_on_fail: boolean };
}

export interface Project {
  slug: string;
  name: string;
  modality: string;
  description: string;
  definition: Definition;
  definition_hash: string;
  output_schema: unknown;
  roles: Role[];
  members: Record<string, { id: string; name: string }[]>;
}

export interface Item { id: number; external_id: string; media_url: string | null; meta: Record<string, any> }

export interface CheckResult { check: string; field: string; severity: "error" | "warning"; passed: boolean; messages: string[] }

export interface Review { reviewer: string; decision: "pass" | "fail"; comment: string; checklist: Record<string, boolean>; at: string }

export interface Version {
  version: number;
  worker: string;
  submitted_at: string;
  data: Record<string, any>;
  checks: CheckResult[];
  review: Review | null;
}

export interface TaskDetail {
  id: number;
  project: { slug: string; name: string; modality: string };
  status: Status;
  assignee: string | null;
  draft: Record<string, any> | null;
  item: Item;
  history: Version[];
  roles: Role[];
}

export interface TaskRow {
  id: number;
  status: Status;
  assignee: string | null;
  external_id: string;
  versions: number;
  last_comment: string | null;
  last_decision: "pass" | "fail" | null;
  last_reviewer: string | null;
  updated_at: string;
}

export class ApiError extends Error {
  constructor(public status: number, public detail: any) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
}

const USER_KEY = "annotate.user";
export const currentUser = () => localStorage.getItem(USER_KEY);
export const setCurrentUser = (id: string | null) =>
  id ? localStorage.setItem(USER_KEY, id) : localStorage.removeItem(USER_KEY);

export async function api<T = any>(path: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: { "Content-Type": "application/json", "X-User": currentUser() ?? "" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data: any = text;
  try { data = text ? JSON.parse(text) : null; } catch { /* plain text response */ }
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? data ?? res.statusText);
  return data as T;
}

/** Load data on mount / when deps change; `reload` re-fetches. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    fn().then((d) => { setData(d); setError(null); }, (e) => setError(String(e.message ?? e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(load, [load]);
  return { data, error, reload: load };
}
