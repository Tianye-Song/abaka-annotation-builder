import { useState } from "react";
import { Link } from "react-router-dom";
import { api, apiForm, authHeaders, outcome, useLoad, type Item, type ProjectStatus, type Status, type User } from "../api";
import { StatusBadge } from "../components/common";
import { useProject } from "./ProjectLayout";

interface Overview {
  items: number;
  no_task: number;
  status_counts: Record<Status, number>;
  reviews: number;
  pass_rate: number | null;
  first_pass_rate: number | null;
  workers: { id: string; name: string; assigned: number; open: number; passed: number; reviews: number; pass_rate: number | null }[];
  reviewers: { id: string; name: string; assigned: number; waiting: number; reviewed: number; passes: number; fails: number; pass_rate: number | null }[];
  rows: { item: Item; task_id: number | null; status: Status | null; assignee: string | null; reviewer_id: string | null; versions: number | null; last_decision: string | null }[];
}

/** Workflow order, used for the status filter and for sorting by status. */
const STATUS_ORDER = ["none", "unassigned", "assigned", "submitted", "failed", "passed"] as const;
const STATUS_LABEL: Record<(typeof STATUS_ORDER)[number], string> = {
  none: "no task", unassigned: "unassigned", assigned: "assigned", submitted: "awaiting review", failed: "rework", passed: "passed",
};

const pct = (x: number | null) => (x === null ? "—" : `${Math.round(x * 100)}%`);

export function AdminView() {
  const p = useProject();
  const { data: o, error, reload } = useLoad(() => api<Overview>(`/projects/${p.slug}/overview`), [p.slug]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [worker, setWorker] = useState<string>("");
  const [reviewer, setReviewer] = useState<string>("");
  const [show, setShow] = useState<Status | "none" | "">(""); // status filter; "" = all
  const [sortBy, setSortBy] = useState<"item" | "status">("item");
  const [msg, setMsg] = useState<string | null>(null);

  const run = async (fn: () => Promise<string>) => {
    setMsg(await outcome(async () => { const m = await fn(); setSelected(new Set()); return m; }));
    reload();
    p.reload();
  };
  const upload = (files: FileList | null) => files?.length && run(async () => {
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f));
    const r = await apiForm(`/projects/${p.slug}/items/upload`, form);
    return `Uploaded ${r.stored} file(s)/line(s); ${r.added} new item(s)`;
  });
  if (error) return <div className="error">{error}</div>;
  if (!o) return <div className="muted">Loading…</div>;

  const rows = o.rows
    .filter((r) => !show || (r.status ?? "none") === show)
    .sort((a, b) => (sortBy === "status" ? STATUS_ORDER.indexOf(a.status ?? "none") - STATUS_ORDER.indexOf(b.status ?? "none") : 0)
      || a.item.id - b.item.id);
  const assignable = rows.filter((r) => r.status === "unassigned" || r.status === "assigned");
  const toggle = (id: number) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const workers = p.members.worker ?? [];
  const reviewers = p.members.reviewer ?? [];
  const sc = o.status_counts;

  const download = async () => {
    const res = await fetch(`/api/projects/${p.slug}/export`, { headers: authHeaders() });
    const url = URL.createObjectURL(await res.blob());
    Object.assign(document.createElement("a"), { href: url, download: `${p.slug}-passed.jsonl` }).click();
  };

  return (
    <div>
      <div className="actions">
        <b>Project status</b>
        <select value={p.status} onChange={(e) => {
          const status = e.target.value as ProjectStatus; // read now: the controlled select resets before the await returns
          run(async () => {
            await api(`/projects/${p.slug}/status`, "PUT", { status });
            return `Project is now ${status}`;
          });
        }}>
          <option value="active">active</option>
          <option value="paused">paused (no new assignments or submissions)</option>
          <option value="archived">archived</option>
        </select>
        <span className="muted small">created by {p.created_by ?? "—"} on {new Date(p.created_at).toLocaleDateString()}</span>
        <span className="grow" />
        <Link to={`/new-project?from=${p.slug}`} className="button-like" title="Start a new project from this project's definition (and optionally its data)">
          Use as template →
        </Link>
      </div>
      <div className="stats">
        <Stat label="Items" value={o.items} />
        <Stat label="Unassigned" value={sc.unassigned} />
        <Stat label="In progress" value={sc.assigned} />
        <Stat label="Awaiting review" value={sc.submitted} />
        <Stat label="In rework" value={sc.failed} />
        <Stat label="Passed" value={sc.passed} />
        <Stat label="Review pass rate" value={pct(o.pass_rate)} sub={`${o.reviews} reviews`} />
        <Stat label="First-pass yield" value={pct(o.first_pass_rate)} sub="passed on v1" />
      </div>
      <div className="progress">
        {(["passed", "submitted", "failed", "assigned", "unassigned"] as Status[]).map((s) => (
          <div key={s} className={`s-${s}`} style={{ flex: sc[s] }} title={`${s}: ${sc[s]}`} />
        ))}
        <div style={{ flex: o.no_task }} className="s-none" title={`no task: ${o.no_task}`} />
      </div>

      <div className="actions">
        <label className="button-like">
          Upload items…
          <input type="file" multiple hidden onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
        </label>
        <button disabled={!o.no_task} onClick={() => run(async () => plural((await api(`/projects/${p.slug}/tasks`, "POST", {})).created, "Created"))}>
          Create tasks ({o.no_task} items without one)
        </button>
        <span className="sep" />
        {/* worker and reviewer are picked independently; empty = least-loaded */}
        <select value={worker} onChange={(e) => setWorker(e.target.value)} title="Worker">
          <option value="">Worker: auto-balance</option>
          {workers.map((w) => <option key={w.id} value={w.id}>Worker: {w.name}</option>)}
        </select>
        <select value={reviewer} onChange={(e) => setReviewer(e.target.value)} title="Reviewer">
          <option value="">Reviewer: auto-balance</option>
          {reviewers.filter((r) => r.id !== worker).map((r) => <option key={r.id} value={r.id}>Reviewer: {r.name}</option>)}
        </select>
        <button className="primary" disabled={!selected.size}
          onClick={() => run(async () => {
            const r = await api(`/projects/${p.slug}/tasks/assign`, "POST", { task_ids: [...selected], worker: worker || null, reviewer: reviewer || null });
            return plural(r.assigned.length, "Assigned");
          })}>
          Assign {selected.size || ""} selected
        </button>
        <span className="sep" />
        <button onClick={download} disabled={!sc.passed}>Export passed (JSONL)</button>
      </div>
      {msg && <div className="flash">{msg}</div>}

      <div className="actions">
        <select value={show} onChange={(e) => { setShow(e.target.value as typeof show); setSelected(new Set()); }}>
          <option value="">Filter: all statuses</option>
          {STATUS_ORDER.map((s) => <option key={s} value={s}>Filter: {STATUS_LABEL[s]}</option>)}
        </select>
        <select value={sortBy} onChange={(e) => setSortBy(e.target.value as typeof sortBy)}>
          <option value="item">Sort: by item</option>
          <option value="status">Sort: by status</option>
        </select>
        <span className="muted small">{rows.length} of {o.rows.length} items</span>
      </div>

      <table className="grid">
        <thead>
          <tr>
            <th>
              <input type="checkbox"
                checked={assignable.length > 0 && assignable.every((r) => selected.has(r.task_id!))}
                onChange={(e) => setSelected(new Set(e.target.checked ? assignable.map((r) => r.task_id!) : []))} />
            </th>
            <th>Item</th><th>Status</th><th>Worker</th><th>Reviewer</th><th>Versions</th><th>Last review</th><th />
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={8} className="muted">No items with this status.</td></tr>}
          {rows.map((r) => (
            <tr key={r.item.id}>
              <td>{r.task_id && (r.status === "unassigned" || r.status === "assigned") &&
                <input type="checkbox" checked={selected.has(r.task_id)} onChange={() => toggle(r.task_id!)} />}</td>
              <td className="mono">{r.item.external_id}</td>
              <td><StatusBadge status={r.status} /></td>
              <td>{r.assignee ?? <span className="muted">—</span>}</td>
              <td>{r.reviewer_id ?? <span className="muted">—</span>}</td>
              <td>{r.versions || <span className="muted">—</span>}</td>
              <td>{r.last_decision ?? <span className="muted">—</span>}</td>
              <td>{r.task_id && <Link to={`../task/${r.task_id}`}>view</Link>}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <Team onChange={(m) => { setMsg(m); reload(); p.reload(); }} />

      <h3>Worker progress</h3>
      <table className="grid">
        <thead><tr><th>Worker</th><th>Assigned</th><th>Open</th><th>Passed</th><th>Reviews</th><th>Pass rate</th></tr></thead>
        <tbody>
          {o.workers.length === 0 && <tr><td colSpan={6} className="muted">No workers yet. Add the team above.</td></tr>}
          {o.workers.map((w) => (
            <tr key={w.id}>
              <td>{w.name}</td><td>{w.assigned}</td><td>{w.open}</td><td>{w.passed}</td><td>{w.reviews}</td><td>{pct(w.pass_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Reviewer progress</h3>
      <table className="grid">
        <thead><tr><th>Reviewer</th><th>Assigned</th><th>Waiting</th><th>Reviewed</th><th>Passed</th><th>Failed</th><th>Pass rate</th></tr></thead>
        <tbody>
          {o.reviewers.length === 0 && <tr><td colSpan={7} className="muted">No reviewers yet. Add the team above.</td></tr>}
          {o.reviewers.map((r) => (
            <tr key={r.id}>
              <td>{r.name}</td><td>{r.assigned}</td><td>{r.waiting}</td><td>{r.reviewed}</td><td>{r.passes}</td><td>{r.fails}</td><td>{pct(r.pass_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {sub && <div className="muted small">{sub}</div>}
    </div>
  );
}

/** The project's team: workers and reviewers, independent of each other. Each task's reviewer is picked when it's assigned. */
function Team({ onChange }: { onChange: (msg: string) => void }) {
  const p = useProject();
  const { data: users } = useLoad(() => api<User[]>("/users"), []);
  const act = async (fn: () => Promise<unknown>, ok: string) => onChange(await outcome(async () => { await fn(); return ok; }));
  return (
    <>
      <h3>Team</h3>
      <div className="team">
        {(["worker", "reviewer"] as const).map((role) => (
          <TeamList key={role} role={role} members={p.members[role] ?? []} users={users ?? []} act={act} />
        ))}
      </div>
    </>
  );
}

function TeamList({ role, members, users, act }: {
  role: "worker" | "reviewer"; members: { id: string; name: string }[]; users: User[];
  act: (fn: () => Promise<unknown>, ok: string) => void;
}) {
  const p = useProject();
  const [pick, setPick] = useState("");
  const on = new Set(members.map((m) => m.id));
  return (
    <table className="grid">
      <thead><tr><th>{role === "worker" ? "Workers" : "Reviewers"}</th><th /></tr></thead>
      <tbody>
        {members.length === 0 && <tr><td colSpan={2} className="muted">Nobody yet.</td></tr>}
        {members.map((m) => (
          <tr key={m.id}>
            <td>{m.name}</td>
            <td><button className="link danger" onClick={() => act(() => api(`/projects/${p.slug}/members/${role}/${m.id}`, "DELETE"), `Removed ${m.id} as ${role}`)}>remove</button></td>
          </tr>
        ))}
        <tr>
          <td>
            <select value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="">Add {role}…</option>
              {users.filter((u) => u.roles.includes(role) && !on.has(u.id)).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
          </td>
          <td>
            <button className="primary" disabled={!pick} onClick={() => act(async () => {
              await api(`/projects/${p.slug}/members`, "POST", { user_id: pick, role });
              setPick("");
            }, `Added ${pick} as ${role}`)}>Add</button>
          </td>
        </tr>
      </tbody>
    </table>
  );
}

const plural = (n: number, verb: string) => `${verb} ${n} task${n === 1 ? "" : "s"}`;
