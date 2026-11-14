import { useEffect, useState } from "react";
import { api, type Derived } from "../api";
import { WIDGETS } from "../fields";
import { ProblemList } from "./common";

type Validation = { ok: boolean; derived?: Derived; problems?: string[] };

/**
 * YAML editor with live validation: as the admin types, the server checks the
 * definition and shows exactly what the platform will generate from it.
 */
export function DefinitionEditor({ value, onChange, onValid, readOnly = false }: {
  value: string;
  onChange: (v: string) => void;
  onValid?: (d: Derived | null) => void;
  readOnly?: boolean;
}) {
  const [result, setResult] = useState<Validation | null>(null);

  useEffect(() => {
    const t = window.setTimeout(async () => {
      const r = await api<Validation>("/projects/validate", "POST", { yaml: value });
      setResult(r);
      onValid?.(r.ok ? r.derived! : null);
    }, 400);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <div className="split">
      <div className="left">
        <textarea className="yaml" spellCheck={false} value={value} readOnly={readOnly} onChange={(e) => onChange(e.target.value)} />
      </div>
      <div className="right">
        {!result && <div className="muted">Checking…</div>}
        {result && !result.ok && (
          <>
            <h4 className="bad-text">✗ Definition has problems</h4>
            <ProblemList problems={result.problems!} />
          </>
        )}
        {result?.ok && <DerivedView d={result.derived!} />}
      </div>
    </div>
  );
}

export function DerivedView({ d }: { d: Derived }) {
  return (
    <div>
      <h4 className="ok-text">✓ Valid. The platform will generate:</h4>
      <ul className="derived">
        <li><b>{d.name}</b> <span className="muted">({d.slug}, {d.modality})</span></li>
        <li>
          <b>Data</b>: {d.data.kind === "files"
            ? <>one item per uploaded file matching <code>{d.data.glob}</code></>
            : <>one item per line of an uploaded <code>.jsonl</code> file (each line needs an <code>id</code>)</>}
        </li>
        <li>
          <b>Worker controls</b>:
          <ul>
            {d.fields.map((f) => (
              <li key={f.id}>
                {f.label}{f.required && <span className="req">*</span>} → <code>{f.type}</code>
                {WIDGETS[f.type]?.surface && <span className="muted"> (drawn on the media)</span>}
              </li>
            ))}
          </ul>
        </li>
        <li><b>Automatic checks</b>: {d.checks.length ? d.checks.join("; ") : <span className="muted">none</span>}</li>
        <li><b>Reviewer checklist</b>: {d.checklist.length ? d.checklist.join("; ") : <span className="muted">none</span>}</li>
        <li><b>Shared for free</b>: login and roles, team and assignment, task lifecycle and rework loop, progress, export</li>
      </ul>
      <details>
        <summary className="muted small">Output JSON Schema</summary>
        <pre className="json">{JSON.stringify(d.output_schema, null, 2)}</pre>
      </details>
    </div>
  );
}
