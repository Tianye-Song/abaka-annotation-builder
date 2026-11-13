import { Link, useNavigate } from "react-router-dom";
import { api, currentUser, setCurrentUser, useLoad } from "../api";

interface UserRow { id: string; name: string; projects: { slug: string; name: string; role: string }[] }
interface MyProject {
  slug: string; name: string; modality: string; roles: string[];
  counts: { todo: number; rework: number; to_review: number; unassigned: number; passed: number; tasks: number };
}

const ICON: Record<string, string> = { audio: "🎧", image: "🖼️", text: "📝" };
const VIEW: Record<string, string> = { admin: "admin", worker: "work", reviewer: "review" };

/** Mock auth: pick a user. Shows each user's roles so the demo is easy to drive. */
export function Login() {
  const nav = useNavigate();
  const { data: users } = useLoad(() => api<UserRow[]>("/users"), []);
  return (
    <div className="narrow">
      <h1>Sign in</h1>
      <p className="muted">Mock login: choose who you are.</p>
      <div className="cards">
        {users?.map((u) => (
          <button key={u.id} className="card user-card" onClick={() => { setCurrentUser(u.id); nav("/"); }}>
            <b>{u.name}</b> <span className="muted">@{u.id}</span>
            <div className="small">
              {u.projects.map((p, i) => <span key={i} className={`role r-${p.role}`}>{p.role} · {p.slug}</span>)}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

/** Unified portal: every project you belong to, your role(s), and what's waiting for you. */
export function Portal() {
  const { data, error } = useLoad(() => api<MyProject[]>("/me/projects"), []);
  return (
    <div className="narrow">
      <h1>Your projects</h1>
      {error && <div className="error">{error}</div>}
      {data?.length === 0 && <p className="muted">You aren't a member of any project.</p>}
      <div className="cards">
        {data?.map((p) => (
          <div key={p.slug} className="card">
            <div className="card-title">{ICON[p.modality]} {p.name}</div>
            <div className="muted small">{p.slug} · {p.counts.passed}/{p.counts.tasks} tasks passed</div>
            <div className="role-links">
              {p.roles.map((r) => {
                const hint =
                  r === "worker" ? `${p.counts.todo} to do${p.counts.rework ? ` · ${p.counts.rework} rework` : ""}`
                  : r === "reviewer" ? `${p.counts.to_review} to review`
                  : `${p.counts.unassigned} unassigned`;
                return (
                  <Link key={r} to={`/p/${p.slug}/${VIEW[r]}`} className={`role-link r-${r}`}>
                    <b>{r}</b> <span className="small">{hint}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <p className="muted small">Signed in as {currentUser()}.</p>
    </div>
  );
}
