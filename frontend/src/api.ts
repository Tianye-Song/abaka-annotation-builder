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
  modality: "audio" | "image" | "text" | "code";
  description: string;
  display: Panel[];
  task: { instructions: string; fields: FieldDef[]; checks: { check: string; severity: string; field: string }[] };
  review: { checklist: string[]; require_full_checklist_to_pass: boolean; require_comment_on_fail: boolean };
}

export type ProjectStatus = "active" | "paused" | "archived";

export interface Project {
  slug: string;
  name: string;
  modality: string;
  status: ProjectStatus;
  description: string;
  created_by: string | null;
  created_at: string;
  definition_yaml: string;
  definition: Definition;
  definition_hash: string;
  output_schema: unknown;
  roles: Role[];
  members: Record<string, { id: string; name: string }[]>;
  reload: () => void; // added by ProjectLayout
}

export const ROLES: Role[] = ["admin", "worker", "reviewer"];

/** The signed-in account and its account roles (from /me). */
export interface Me { id: string; name: string; roles: Role[] }

export interface User { id: string; name: string; roles: Role[]; projects: { slug: string; name: string; role: Role }[] }

/** What the platform will generate from a definition (from /projects/validate). */
export interface Derived {
  slug: string; name: string; modality: string;
  fields: { id: string; type: string; label: string; required: boolean }[];
  checks: string[]; checklist: string[];
  data: { kind: "files" | "jsonl"; path: string; glob: string };
  output_schema: unknown;
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
  reviewer: string | null;
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

// Session: the token from /api/login (never the password). By default it lasts for this browser
// tab only; with "Remember me" it is kept in localStorage, so the user stays signed in after
// closing the browser, until they sign out.
const TOKEN_KEY = "annotate.token";
const USER_KEY = "annotate.user";
const stores = (): Storage[] => {
  try { return [sessionStorage, localStorage]; } catch { return []; }
};
const read = (key: string) => {
  for (const s of stores()) { try { const v = s.getItem(key); if (v) return v; } catch { /* storage blocked */ } }
  return null;
};
export const currentUser = () => read(USER_KEY);
export const authHeaders = (): Record<string, string> => {
  const t = read(TOKEN_KEY);
  return t ? { Authorization: `Bearer ${t}` } : {};
};
export function startSession(token: string, userId: string, remember = false) {
  clearSession();
  try {
    const s = remember ? localStorage : sessionStorage;
    s.setItem(TOKEN_KEY, token);
    s.setItem(USER_KEY, userId);
  } catch { /* storage blocked: the sign-in won't persist */ }
}
function clearSession() {
  for (const s of stores()) { try { s.removeItem(TOKEN_KEY); s.removeItem(USER_KEY); } catch { /* ignore */ } }
}
export async function signOut() {
  await fetch("/api/logout", { method: "POST", headers: authHeaders() }).catch(() => {});
  clearSession();
}

/** Every API call: auth header, JSON (or plain-text) response, 401 → back to the login page. */
async function request<T>(path: string, init: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { ...init, headers: { ...init.headers, ...authHeaders() } });
  const text = await res.text();
  let data: any = text;
  try { data = text ? JSON.parse(text) : null; } catch { /* plain text response */ }
  if (res.status === 401 && path !== "/login") {
    clearSession();
    if (!location.pathname.startsWith("/login")) location.assign("/login");
  }
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? data ?? res.statusText);
  return data as T;
}

export const api = <T = any>(path: string, method = "GET", body?: unknown) =>
  request<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

/** Multipart upload (definition + data files). */
export const apiForm = <T = any>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form });

/** Human-readable error lines from an API error (definition problems come as a list). */
export function problemsOf(e: unknown): string[] {
  if (e instanceof ApiError && e.detail && typeof e.detail === "object" && Array.isArray(e.detail.problems)) return e.detail.problems;
  return [String((e as Error)?.message ?? e)];
}

/** Run an action and turn its outcome into a one-line flash message (its own text, or the error). */
export async function outcome(fn: () => Promise<string>): Promise<string> {
  try { return await fn(); } catch (e) { return `Error: ${problemsOf(e).join("; ")}`; }
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
