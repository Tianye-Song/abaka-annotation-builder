import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Link, Navigate, Outlet, Route, Routes, useNavigate } from "react-router-dom";
import { currentUser, setCurrentUser } from "./api";
import { AdminView } from "./pages/AdminView";
import { DefinitionView } from "./pages/DefinitionView";
import { Login, Portal } from "./pages/Portal";
import { ProjectHome, ProjectLayout } from "./pages/ProjectLayout";
import { ReviewQueue, WorkerQueue } from "./pages/Queues";
import { TaskPage } from "./pages/TaskPage";
import "./styles.css";

function Shell() {
  const nav = useNavigate();
  const user = currentUser();
  if (!user) return <Navigate to="/login" replace />;
  return (
    <>
      <header className="top">
        <Link to="/" className="brand">◧ Annotation Platform</Link>
        <span className="grow" />
        <span className="muted">@{user}</span>
        <button className="link" onClick={() => { setCurrentUser(null); nav("/login"); }}>switch user</button>
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
