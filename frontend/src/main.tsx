import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Link, Navigate, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, currentUser, signOut, useLoad, type Me } from "./api";
import { AdminView } from "./pages/AdminView";
import { DefinitionView } from "./pages/DefinitionView";
import { NewProject } from "./pages/NewProject";
import { Login, Portal } from "./pages/Portal";
import { ProjectHome, ProjectLayout } from "./pages/ProjectLayout";
import { ReviewQueue, WorkerQueue } from "./pages/Queues";
import { TaskPage } from "./pages/TaskPage";
import { UsersPage } from "./pages/UsersPage";
import "./styles.css";

function Shell() {
  const nav = useNavigate();
  const here = useLocation().pathname;
  const user = currentUser();
  const { data: me } = useLoad(() => (user ? api<Me>("/me") : Promise.resolve(null)), [user]);
  if (!user) return <Navigate to="/login" replace />;
  return (
    <>
      <header className="top">
        <Link to="/" className="brand">◧ Annotation Platform</Link>
        <span className="grow" />
        {/* An admin's name opens the Users page; for everyone else it's just their name.
            On the Users page it's left out: the list marks the current account instead. */}
        {here === "/users" ? null
          : me?.roles.includes("admin")
            ? <Link to="/users" className="user-link" title="Manage users">{me.name}</Link>
            : <span className="muted">{me?.name ?? user}</span>}
        <button className="link" onClick={async () => { await signOut(); nav("/login"); }}>sign out</button>
      </header>
      <Outlet />
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<Shell />}>
          <Route path="/" element={<Portal />} />
          <Route path="/new-project" element={<NewProject />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="/p/:slug" element={<ProjectLayout />}>
            <Route index element={<ProjectHome />} />
            <Route path="admin" element={<AdminView />} />
            <Route path="work" element={<WorkerQueue />} />
            <Route path="review" element={<ReviewQueue />} />
            <Route path="task/:taskId" element={<TaskPage />} />
            <Route path="definition" element={<DefinitionView />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
