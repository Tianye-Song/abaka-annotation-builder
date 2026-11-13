import { api, useLoad } from "../api";
import { WIDGETS } from "../fields";
import { useProject } from "./ProjectLayout";

/** Shows what the project author wrote, and what the platform derived from it. */
export function DefinitionView() {
  const p = useProject();
  const d = p.definition;
  const { data: yaml } = useLoad(() => api<string>(`/projects/${p.slug}/definition.yaml`), [p.slug]);
  return (
    <div className="split">
      <div className="left">
        <h3>What the author wrote <span className="muted small">projects/{p.slug}/project.yaml</span></h3>
        <pre className="json">{yaml}</pre>
      </div>
      <div className="right">
        <h3>What the platform generated</h3>
        <ul className="derived">
          <li><b>Item loader</b>: {d.modality} items from the data source ({d.display.length} display panels)</li>
          <li><b>Worker controls</b>: {d.task.fields.map((f) => `${f.label ?? f.id} → ${f.type}${WIDGETS[f.type]?.surface ? " (on the media)" : ""}`).join("; ")}</li>
          <li><b>Submit-time validation</b>: the output JSON Schema below + {d.task.checks.length} automatic check(s)</li>
          <li><b>Review screen</b>: read-only annotation, check results, {d.review.checklist.length}-item checklist, pass/fail with comment</li>
          <li><b>Shared for free</b>: users &amp; roles, assignment, lifecycle and rework loop, progress/pass rate, history, export</li>
        </ul>
        <div className="muted small">definition hash {p.definition_hash}</div>
        <h4>Output schema</h4>
        <pre className="json">{JSON.stringify(p.output_schema, null, 2)}</pre>
      </div>
    </div>
  );
}
