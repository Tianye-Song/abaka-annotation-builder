import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { api, currentUser, startSession, useLoad, type Me } from "../api";
import { MODALITY_ICON, ProjectStatusBadge } from "../components/common";
import { TABS } from "./ProjectLayout";

interface MyProject {
  slug: string; name: string; modality: string; status: string; roles: string[];
  counts: { todo: number; rework: number; to_review: number; unassigned: number; passed: number; tasks: number };
}

/** Sign in: choose an account, enter its password. */
export function Login() {
  const nav = useNavigate();
  const { data: accounts } = useLoad(() => api<{ id: string; name: string }[]>("/accounts"), []);
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [remember, setRemember] = useState(false);
  const signIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ token: string; user: { id: string } }>("/login", "POST", { user_id: user, password });
      startSession(r.token, r.user.id, remember);
      nav("/");
    } catch {
      setError("Wrong account or password.");
      setPassword("");
    } finally {
      setBusy(false);
    }
  };
  if (currentUser()) return <Navigate to="/" replace />; // remembered sign-in
  return (
    <div className="login-page">
      <form className="login-card" onSubmit={signIn}>
        <div className="brand login-brand">◧ Annotation Platform</div>
        <h1>Sign in</h1>
        <label className="field-label" htmlFor="account">Account</label>
        <select id="account" value={user} onChange={(e) => { setUser(e.target.value); setError(null); }}>
          <option value="" disabled>Select an account…</option>
          {accounts?.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
        </select>
        {/* lets the browser's password manager pair the saved password with this account */}
        <input type="text" name="username" autoComplete="username" value={user} readOnly hidden />
        <label className="field-label" htmlFor="password">Password</label>
        <input id="password" name="password" type="password" autoComplete="current-password" value={password}
          onChange={(e) => { setPassword(e.target.value); setError(null); }} />
        <label className="check-row">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Remember me
        </label>
        {error && <div className="error">{error}</div>}
        <button type="submit" className="primary" disabled={!user || !password || busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </div>
  );
}

/** What's waiting for this role in this project, shown on its link. */
function waiting(role: string, c: MyProject["counts"]): string {
  if (role === "worker") return `${c.todo} to do${c.rework ? ` · ${c.rework} rework` : ""}`;
  if (role === "reviewer") return `${c.to_review} to review`;
  return `${c.unassigned} unassigned`;
}

/**
 * Unified portal: every project you can access, your role in each, and what's waiting for you.
 * Each role links straight to its view; clicking the card opens your first one.
 */
export function Portal() {
  const nav = useNavigate();
  const { data: me } = useLoad(() => api<Me>("/me"), []);
  const { data, error } = useLoad(() => api<MyProject[]>("/me/projects"), []);
  const isAdmin = !!me?.roles.includes("admin");
  const open = (p: MyProject) => nav(`/p/${p.slug}`);
  return (
    <div className="narrow">
      <div className="actions">
        <h1 className="grow">Your projects</h1>
        {isAdmin && <Link to="/new-project" className="button-like primary">+ New project</Link>}
      </div>
      {error && <div className="error">{error}</div>}
      {data?.length === 0 && <p className="muted">No projects yet{isAdmin ? "" : ": an admin adds you to a project's team"}.</p>}
      <div className="cards">
        {data?.map((p) => (
          <div
            key={p.slug}
            className="card clickable"
            role="link"
            tabIndex={0}
            title={`Open ${p.name}`}
            onClick={() => open(p)}
            onKeyDown={(e) => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); open(p); } }}
          >
            <div className="card-title">
              {MODALITY_ICON[p.modality]} {p.name} <ProjectStatusBadge status={p.status} />
            </div>
            <div className="muted small">{p.slug} · {p.counts.passed}/{p.counts.tasks} tasks passed <span className="open-hint">Open →</span></div>
            <div className="role-links">
              {TABS.filter((t) => p.roles.includes(t.role)).map((t) => (
                <Link key={t.role} to={`/p/${p.slug}/${t.path}`} className={`role-tag r-${t.role}`}
                  title={`Open ${t.label}`} onClick={(e) => e.stopPropagation()}>
                  <b>{t.role}</b> <span className="small">{waiting(t.role, p.counts)}</span> →
                </Link>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
