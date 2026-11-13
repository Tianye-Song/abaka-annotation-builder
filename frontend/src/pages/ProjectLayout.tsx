import { NavLink, Navigate, Outlet, useOutletContext, useParams } from "react-router-dom";
import { api, useLoad, type Project } from "../api";

export const useProject = () => useOutletContext<Project>();

const TABS = [
  { role: "admin", path: "admin", label: "Admin" },
  { role: "worker", path: "work", label: "My tasks" },
  { role: "reviewer", path: "review", label: "Review" },
] as const;

/** Shell for every project: the same tabs, filtered by the viewer's roles in this project. */
export function ProjectLayout() {
  const { slug } = useParams();
  const { data: project, error } = useLoad(() => api<Project>(`/projects/${slug}`), [slug]);
  if (error) return <div className="error page">{error}</div>;
  if (!project) return <div className="page muted">Loading…</div>;
  return (
    <div>
      <div className="project-bar">
        <div>
          <div className="project-name">{project.name}</div>
          <div className="muted small">{project.description}</div>
        </div>
        <nav className="tabs">
          {TABS.filter((t) => project.roles.includes(t.role)).map((t) => (
            <NavLink key={t.path} to={t.path}>{t.label}</NavLink>
          ))}
          <NavLink to="definition">Definition</NavLink>
        </nav>
      </div>
      <div className="page">
        <Outlet context={project} />
      </div>
    </div>
  );
}

export function ProjectHome() {
  const p = useProject();
  const first = TABS.find((t) => p.roles.includes(t.role));
  return <Navigate to={first ? first.path : "definition"} replace />;
}
