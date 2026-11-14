import { Link, NavLink, Navigate, Outlet, useLocation, useOutletContext, useParams } from "react-router-dom";
import { api, useLoad, type Project } from "../api";
import { ProjectStatusBadge } from "../components/common";

export const useProject = () => useOutletContext<Project>();

/** Each project role's own view. The portal (← Projects) links straight to these. */
export const TABS = [
  { role: "admin", path: "admin", label: "Admin" },
  { role: "worker", path: "work", label: "My tasks" },
  { role: "reviewer", path: "review", label: "Review" },
] as const;

/**
 * Shell for every project. No role tabs: "← Projects" goes back to the portal, which lists every
 * project and links to each of your views in it (admin / worker / reviewer).
 */
export function ProjectLayout() {
  const { slug } = useParams();
  const section = useLocation().pathname.split("/")[3]; // /p/<slug>/<section>
  const view = TABS.find((t) => t.path === section)?.label;
  const { data, error, reload } = useLoad(() => api<Project>(`/projects/${slug}`), [slug]);
  const project = data && { ...data, reload };
  if (error) return <div className="error page">{error}</div>;
  if (!project) return <div className="page muted">Loading…</div>;
  return (
    <div>
      <div className="project-bar">
        <div>
          <Link to="/" className="button-like back-to-projects">← Projects</Link>
        </div>
        <div className="grow">
          <div className="project-name">
            {project.name} <ProjectStatusBadge status={project.status} />
            {view && <span className="muted small"> · {view}</span>}
          </div>
          <div className="muted small">{project.description}</div>
        </div>
        <nav className="tabs">
          {/* Admin view only: in the worker / reviewer views it's hidden even for someone who is also an admin */}
          {project.roles.includes("admin") && (section === "admin" || section === "definition") && <NavLink to="definition">Definition</NavLink>}
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
  return <Navigate to={first ? first.path : "/"} replace />;
}
