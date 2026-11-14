import type { CheckResult, Definition, FieldDef, Item, Panel, Status, Version } from "../api";
import { WIDGETS, isRequired } from "../fields";

export const MODALITY_ICON: Record<string, string> = { audio: "🎧", image: "🖼️", text: "📝", code: "💻" };

/** Shown next to a project name only when it isn't active. */
export function ProjectStatusBadge({ status }: { status: string }) {
  return status === "active" ? null : <span className={`badge st-${status}`}>{status}</span>;
}

/** A list of blocking problems (bad definition, failed create, schema errors). */
export function ProblemList({ problems }: { problems: string[] }) {
  return <ul className="checks">{problems.map((p, i) => <li key={i} className="bad">✗ {p}</li>)}</ul>;
}

export function StatusBadge({ status }: { status: Status | null }) {
  const label: Record<string, string> = { failed: "rework", unassigned: "unassigned" };
  return <span className={`badge s-${status ?? "none"}`}>{status ? label[status] ?? status : "no task"}</span>;
}

/** Tiny, safe markdown: escape, then **bold**, *italic*, `code`; blank line = paragraph break. */
export function Md({ text }: { text: string }) {
  const esc = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const html = esc
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\*([^*]+)\*/g, "<i>$1</i>")
    .replace(/\n\s*\n/g, "<br/><br/>")
    .replace(/\n/g, " ");
  return <span dangerouslySetInnerHTML={{ __html: html }} />;
}

function PanelView({ panel, value }: { panel: Panel; value: any }) {
  const body =
    panel.format === "code" ? (
      <pre className="code">
        {String(value ?? "").split("\n").map((line, i) => (
          <div key={i}><span className="ln">{i + 1}</span>{line || " "}</div>
        ))}
      </pre>
    ) : panel.format === "markdown" ? <div className="prose"><Md text={String(value ?? "")} /></div>
      : <div className="prose">{String(value ?? "")}</div>;
  return (
    <div className="panel">
      <div className="panel-label">{panel.label ?? panel.key}</div>
      {body}
    </div>
  );
}

/** The item as the definition says to show it. Media is drawn here unless a surface widget owns it. */
export function ItemView({ def, item, hideMedia }: { def: Definition; item: Item; hideMedia: boolean }) {
  return (
    <div className="item-view">
      {!hideMedia && item.media_url && def.modality === "image" && <img className="media" src={item.media_url} alt="" />}
      {!hideMedia && item.media_url && def.modality === "audio" && <audio controls src={item.media_url} />}
      {def.display.map((p) => <PanelView key={p.key} panel={p} value={item.meta[p.key]} />)}
    </div>
  );
}

/** All non-surface fields for a definition, rendered from the widget registry. */
export function FieldList({ fields, values, onChange, item, readOnly }: {
  fields: FieldDef[]; values: Record<string, any>; onChange: (id: string, v: any) => void; item: Item; readOnly: boolean;
}) {
  return (
    <>
      {fields.map((f) => {
        const W = WIDGETS[f.type];
        if (!W) return <div key={f.id} className="error">Unknown field type “{f.type}”</div>;
        return (
          <div key={f.id} className="field">
            <label className="field-label">
              {f.label ?? f.id}
              {isRequired(f, values) && <span className="req">*</span>}
              {f.required_when && <span className="muted small"> (required when {f.required_when.field} = {String(f.required_when.equals)})</span>}
            </label>
            {f.help && <div className="muted small">{f.help}</div>}
            <W.component field={f} value={values[f.id]} onChange={(v) => onChange(f.id, v)} item={item} readOnly={readOnly} />
          </div>
        );
      })}
    </>
  );
}

export function ChecksList({ checks, schemaErrors = [] }: { checks: CheckResult[]; schemaErrors?: string[] }) {
  if (!checks.length && !schemaErrors.length) return null;
  return (
    <ul className="checks">
      {schemaErrors.map((e, i) => <li key={`s${i}`} className="bad">✗ {e}</li>)}
      {checks.map((c, i) => (
        <li key={i} className={c.passed ? "ok" : c.severity === "error" ? "bad" : "warn"}>
          {c.passed ? "✓" : c.severity === "error" ? "✗" : "⚠"} <b>{c.check}</b> <span className="muted">({c.field})</span>
          {c.messages.map((m, j) => <div key={j} className="small">{m}</div>)}
        </li>
      ))}
    </ul>
  );
}

export function ReviewNote({ v }: { v: Version }) {
  if (!v.review) return null;
  const r = v.review;
  return (
    <div className={`review-note ${r.decision}`}>
      <b>{r.decision === "pass" ? "Passed" : "Failed"}</b> by {r.reviewer} · v{v.version}
      {r.comment && <div className="comment">“{r.comment}”</div>}
    </div>
  );
}
