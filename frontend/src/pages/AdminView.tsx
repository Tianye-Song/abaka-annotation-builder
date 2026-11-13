import { useState } from "react";
import { Link } from "react-router-dom";
import { api, currentUser, useLoad, type Item, type Status } from "../api";
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
  rows: { item: Item; task_id: number | null; status: Status | null; assignee: string | null; versions: number | null; last_decision: string | null }[];
}

const pct = (x: number | null) => (x === null ? "—" : `${Math.round(x * 100)}%`);

export function AdminView() {
  const p = useProject();
  const { data: o, error, reload } = useLoad(() => api<Overview>(`/projects/${p.slug}/overview`), [p.slug]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [worker, setWorker] = useState<string>("");
  const [msg, setMsg] = useState<string | null>(null);

  const run = async (fn: () => Promise<string>) => {
    try { setMsg(await fn()); setSelected(new Set()); } catch (e: any) { setMsg(`Error: ${e.message}`); }
    reload();
  };
  if (error) return <div className="error">{error}</div>;
  if (!o) return <div className="muted">Loading…</div>;

  const assignable = o.rows.filter((r) => r.status === "unassigned" || r.status === "assigned");
  const toggle = (id: number) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const workers = p.members.worker ?? [];
  const sc = o.status_counts;

  const download = async () => {
    const res = await fetch(`/api/projects/${p.slug}/export`, { headers: { "X-User": currentUser() ?? "" } });
    const url = URL.createObjectURL(await res.blob());
    Object.assign(document.createElement("a"), { href: url, download: `${p.slug}-passed.jsonl` }).click();
  };

  return (
    <div>
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
        <button onClick={() => run(async () => `Loaded ${(await api(`/projects/${p.slug}/items/load`, "POST")).added} new items`)}>
          Load items from source
        </button>
        <button disabled={!o.no_task} onClick={() => run(async () => `Created ${(await api(`/projects/${p.slug}/tasks`, "POST", {})).created} tasks`)}>
          Create tasks ({o.no_task} items without one)
        </button>
        <span className="sep" />
        <select value={worker} onChange={(e) => setWorker(e.target.value)}>
          <option value="">Auto-balance across workers</option>
          {workers.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
        </select>
        <button className="primary" disabled={!selected.size}
          onClick={() => run(async () => {
            const r = await api(`/projects/${p.slug}/tasks/assign`, "POST", { task_ids: [...selected], worker: worker || null });
            return `Assigned ${r.assigned.length} tasks`;
          })}>
          Assign {selected.size || ""} selected
        </button>
        <span className="sep" />
        <button onClick={download} disabled={!sc.passed}>Export passed (JSONL)</button>
      </div>
      {msg && <div className="flash">{msg}</div>}

      <table className="grid">
        <thead>
          <tr>
            <th>
              <input type="checkbox"
                checked={assignable.length > 0 && assignable.every((r) => selected.has(r.task_id!))}
                onChange={(e) => setSelected(new Set(e.target.checked ? assignable.map((r) => r.task_id!) : []))} />
            </th>
            <th>Item</th><th>Status</th><th>Assignee</th><th>Versions</th><th>Last review</th><th />
          </tr>
        </thead>
        <tbody>
          {o.rows.map((r) => (
            <tr key={r.item.id}>
              <td>{r.task_id && (r.status === "unassigned" || r.status === "assigned") &&
                <input type="checkbox" checked={selected.has(r.task_id)} onChange={() => toggle(r.task_id!)} />}</td>
              <td className="mono">{r.item.external_id}</td>
              <td><StatusBadge status={r.status} /></td>
              <td>{r.assignee ?? <span className="muted">—</span>}</td>
              <td>{r.versions || <span className="muted">—</span>}</td>
              <td>{r.last_decision ?? <span className="muted">—</span>}</td>
              <td>{r.task_id && <Link to={`../task/${r.task_id}`}>view</Link>}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Workers</h3>
      <table className="grid">
        <thead><tr><th>Worker</th><th>Assigned</th><th>Open</th><th>Passed</th><th>Reviews</th><th>Pass rate</th></tr></thead>
        <tbody>
          {o.workers.map((w) => (
            <tr key={w.id}>
              <td>{w.name}</td><td>{w.assigned}</td><td>{w.open}</td><td>{w.passed}</td><td>{w.reviews}</td><td>{pct(w.pass_rate)}</td>
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
