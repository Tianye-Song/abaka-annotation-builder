import { Link } from "react-router-dom";
import { api, useLoad, type TaskRow } from "../api";
import { StatusBadge } from "../components/common";
import { useProject } from "./ProjectLayout";

function TaskTable({ rows, showAssignee, empty }: { rows: TaskRow[]; showAssignee?: boolean; empty: string }) {
  if (!rows.length) return <p className="muted">{empty}</p>;
  return (
    <table className="grid">
      <thead>
        <tr><th>Item</th><th>Status</th>{showAssignee && <th>Worker</th>}<th>Version</th><th>Last review</th><th /></tr>
      </thead>
      <tbody>
        {rows.map((t) => (
          <tr key={t.id}>
            <td className="mono">{t.external_id}</td>
            <td><StatusBadge status={t.status} /></td>
            {showAssignee && <td>{t.assignee}</td>}
            <td>{t.versions ? `v${t.versions}` : "—"}</td>
            <td className="comment-cell">
              {t.last_decision ? <><b>{t.last_decision}</b>{t.last_comment && <> · “{t.last_comment}”</>}</> : <span className="muted">—</span>}
            </td>
            <td><Link to={`../task/${t.id}`}>open →</Link></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Worker: rework first (it carries reviewer feedback), then new work, then history. */
export function WorkerQueue() {
  const p = useProject();
  const { data } = useLoad(() => api<TaskRow[]>(`/projects/${p.slug}/my-tasks`), [p.slug]);
  if (!data) return <div className="muted">Loading…</div>;
  const by = (...s: string[]) => data.filter((t) => s.includes(t.status));
  return (
    <div>
      <h3>Needs rework <span className="count">{by("failed").length}</span></h3>
      <TaskTable rows={by("failed")} empty="Nothing sent back to you." />
      <h3>To do <span className="count">{by("assigned").length}</span></h3>
      <TaskTable rows={by("assigned")} empty="No new tasks assigned to you." />
      <h3>Done</h3>
      <TaskTable rows={by("submitted", "passed")} empty="Nothing submitted yet." />
    </div>
  );
}

export function ReviewQueue() {
  const p = useProject();
  const { data } = useLoad(() => api<{ pending: TaskRow[]; done: TaskRow[] }>(`/projects/${p.slug}/review-queue`), [p.slug]);
  if (!data) return <div className="muted">Loading…</div>;
  return (
    <div>
      <h3>Waiting for review <span className="count">{data.pending.length}</span></h3>
      <TaskTable rows={data.pending} showAssignee empty="Queue is empty." />
      <h3>Reviewed by you</h3>
      <TaskTable rows={data.done} showAssignee empty="You haven't reviewed anything yet." />
    </div>
  );
}
