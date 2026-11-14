import { useState } from "react";
import { Navigate } from "react-router-dom";
import { api, problemsOf } from "../api";
import { DefinitionEditor } from "../components/DefinitionEditor";
import { useProject } from "./ProjectLayout";

/** The definition this project runs on. Admins only: workers and reviewers are sent back to their view. */
export function DefinitionView() {
  const p = useProject();
  const isAdmin = p.roles.includes("admin");
  const [yaml, setYaml] = useState(p.definition_yaml);
  const [valid, setValid] = useState(false);
  const [msg, setMsg] = useState<string[]>([]);
  const dirty = yaml !== p.definition_yaml;

  const save = async () => {
    try {
      const r = await api(`/projects/${p.slug}/definition`, "PUT", { yaml });
      setMsg([r.changed ? `Saved as definition ${r.hash}. New submissions are validated against it.` : "No changes."]);
      p.reload();
    } catch (e) {
      setMsg(problemsOf(e));
    }
  };

  if (!isAdmin) return <Navigate to=".." replace />; // back to the viewer's own view

  return (
    <div>
      <div className="actions">
        <span className="muted small">
          created by {p.created_by ?? "—"} · definition {p.definition_hash}
          {isAdmin ? " · edit below; the preview updates as you type" : " · read-only"}
        </span>
        <span className="grow" />
        {isAdmin && (
          <>
            <button disabled={!dirty} onClick={() => { setYaml(p.definition_yaml); setMsg([]); }}>Discard</button>
            <button className="primary" disabled={!dirty || !valid} onClick={save}>Save definition</button>
          </>
        )}
      </div>
      {msg.length > 0 && <div className="flash">{msg.map((m, i) => <div key={i}>{m}</div>)}</div>}
      <DefinitionEditor value={yaml} onChange={setYaml} onValid={(d) => setValid(!!d)} readOnly={!isAdmin} />
    </div>
  );
}
