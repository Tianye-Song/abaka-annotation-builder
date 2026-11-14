import { useState } from "react";
import { Link } from "react-router-dom";
import { ROLES, api, currentUser, outcome, useLoad, type Role, type User } from "../api";

const NEW_USER = { id: "", name: "", roles: ["worker"] as Role[], password: "" };

/** One toggle per account role. `locked` roles can't be unticked (your own admin role). */
function RoleToggles({ roles, onChange, locked = [] }: { roles: Role[]; onChange: (next: Role[]) => void; locked?: Role[] }) {
  const toggle = (r: Role) => {
    const next = roles.includes(r) ? roles.filter((x) => x !== r) : ROLES.filter((x) => x === r || roles.includes(x));
    if (next.length) onChange(next); // an account keeps at least one role
  };
  return (
    <div className="role-toggles">
      {ROLES.map((r) => {
        const on = roles.includes(r), lock = on && locked.includes(r);
        return (
          <label key={r} className={on ? `on r-${r}` : ""}>
            <input type="checkbox" checked={on} disabled={lock} onChange={() => toggle(r)} /> {r}
          </label>
        );
      })}
    </div>
  );
}

/**
 * Admin: the users table. Account roles say what a user may do anywhere (admin: create projects
 * and manage users; worker: be put on teams and assigned jobs; reviewer: review assigned jobs).
 * Which projects they work on is set in each project's Team.
 */
export function UsersPage() {
  const { data: users, reload } = useLoad(() => api<User[]>("/users"), []);
  const [form, setForm] = useState(NEW_USER);
  const [msg, setMsg] = useState<string | null>(null);
  const me = currentUser();
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(await outcome(async () => { await fn(); return ok; }));
    reload();
  };

  return (
    <div className="page narrow-wide">
      <Link to="/" className="button-like back-to-projects">← Projects</Link>
      <h1>Users</h1>
      <p className="muted small">
        <b>admin</b> creates projects and manages users and teams · <b>worker</b> can be put on a team and assigned labeling jobs ·
        {" "}<b>reviewer</b> can be put on a team and assigned jobs to review. One account can hold several roles.
        Who works on which project is set in each project's <b>Team</b>.
      </p>
      {msg && <div className="flash">{msg}</div>}
      <table className="grid">
        <thead><tr><th>User</th><th>Name</th><th>Account roles</th><th>Password</th><th /></tr></thead>
        <tbody>
          {users?.map((u) => (
            <tr key={u.id} className={u.id === me ? "current-account" : undefined}>
              <td className="mono">{u.id}</td>
              <td>{u.name}{u.id === me && <span className="you-tag">you</span>}</td>
              <td>
                <RoleToggles roles={u.roles} locked={u.id === me ? ["admin"] : []}
                  onChange={(roles) => act(() => api(`/users/${u.id}`, "PATCH", { roles }), `${u.id} is now ${roles.join(", ")}`)} />
              </td>
              <td>
                <button className="link" onClick={() => {
                  const pw = window.prompt(`New password for ${u.name} (at least 6 characters)`);
                  if (pw) act(() => api(`/users/${u.id}`, "PATCH", { password: pw }), `Password reset for ${u.id}; their other sessions were signed out`);
                }}>reset</button>
              </td>
              <td>
                {u.id !== me && (
                  <button className="link danger" onClick={() => {
                    if (window.confirm(`Delete ${u.name} (${u.id})? This can't be undone.`))
                      act(() => api(`/users/${u.id}`, "DELETE"), `Deleted ${u.id}`);
                  }}>delete</button>
                )}
              </td>
            </tr>
          ))}
          <tr>
            <td><input type="text" placeholder="id (e.g. frank)" value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value.toLowerCase() })} /></td>
            <td><input type="text" placeholder="Display name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></td>
            <td><RoleToggles roles={form.roles} onChange={(roles) => setForm({ ...form, roles })} /></td>
            <td>
              <input type="password" placeholder="Password (6+ chars)" autoComplete="new-password" value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </td>
            <td>
              <button className="primary" disabled={!form.id || !form.name || form.password.length < 6}
                onClick={() => act(async () => { await api("/users", "POST", form); setForm(NEW_USER); }, `Added ${form.id}`)}>
                Add user
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
