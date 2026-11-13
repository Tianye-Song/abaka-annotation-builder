import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api, currentUser, useLoad, type CheckResult, type TaskDetail } from "../api";
import { ChecksList, FieldList, ItemView, Md, ReviewNote, StatusBadge } from "../components/common";
import { WIDGETS, clean } from "../fields";
import { useProject } from "./ProjectLayout";

type Mode = "annotate" | "review" | "view";

/**
 * One page per task, for every role and every project. The mode comes from who you
 * are and where the task is in its lifecycle; the controls come from the definition.
 */
export function TaskPage() {
  const p = useProject();
  const def = p.definition;
  const { taskId } = useParams();
  const nav = useNavigate();
  const { data: task, error, reload } = useLoad(() => api<TaskDetail>(`/tasks/${taskId}`), [taskId]);

  if (error) return <div className="error">{error}</div>;
  if (!task) return <div className="muted">Loading…</div>;

  const me = currentUser();
  const mode: Mode =
    task.roles.includes("worker") && task.assignee === me && (task.status === "assigned" || task.status === "failed") ? "annotate"
    : task.roles.includes("reviewer") && task.status === "submitted" && task.assignee !== me ? "review"
    : "view";
  const latest = task.history[task.history.length - 1];
  const back = mode === "annotate" ? "../work" : mode === "review" ? "../review" : -1;

  return (
    <div>
      <div className="task-head">
        <button className="link" onClick={() => (typeof back === "number" ? nav(back) : nav(back))}>← back</button>
        <span className="mono">{task.item.external_id}</span>
        <StatusBadge status={task.status} />
        <span className="muted small">assignee: {task.assignee ?? "—"} · {task.history.length} version(s) · mode: {mode}</span>
      </div>
      {mode === "annotate" ? (
        <Annotate key={task.id} task={task} onDone={() => nav("../work")} />
      ) : (
        <Inspect key={`${task.id}-${task.status}`} task={task} canReview={mode === "review"} onDone={() => { reload(); nav("../review"); }} />
      )}
      {task.history.length > 0 && (
        <details className="history" open={mode === "view"}>
          <summary>History ({task.history.length} submission{task.history.length > 1 ? "s" : ""})</summary>
          {[...task.history].reverse().map((v) => (
            <div key={v.version} className="history-row">
              <b>v{v.version}</b> by {v.worker} · {new Date(v.submitted_at).toLocaleString()}
              {v.review ? <ReviewNote v={v} /> : <span className="muted"> · awaiting review</span>}
              {v !== latest && <pre className="json">{JSON.stringify(v.data, null, 2)}</pre>}
            </div>
          ))}
        </details>
      )}
      <p className="muted small">Definition: <Link to="../definition">{def.slug}</Link></p>
    </div>
  );
}

function Split({ task, values, onChange, readOnly, children }: {
  task: TaskDetail; values: Record<string, any>; onChange: (id: string, v: any) => void; readOnly: boolean; children: React.ReactNode;
}) {
  const def = useProject().definition;
  const surface = def.task.fields.filter((f) => WIDGETS[f.type]?.surface);
  const rest = def.task.fields.filter((f) => !WIDGETS[f.type]?.surface);
  return (
    <div className="split">
      <div className="left">
        <ItemView def={def} item={task.item} hideMedia={surface.length > 0} />
        <FieldList fields={surface} values={values} onChange={onChange} item={task.item} readOnly={readOnly} />
      </div>
      <div className="right">
        {def.task.instructions && <div className="instructions"><Md text={def.task.instructions} /></div>}
        <FieldList fields={rest} values={values} onChange={onChange} item={task.item} readOnly={readOnly} />
        {children}
      </div>
    </div>
  );
}

function Annotate({ task, onDone }: { task: TaskDetail; onDone: () => void }) {
  const latest = task.history[task.history.length - 1];
  const [values, setValues] = useState<Record<string, any>>(() => task.draft ?? latest?.data ?? {});
  const [checks, setChecks] = useState<CheckResult[]>([]);
  const [schemaErrors, setSchemaErrors] = useState<string[]>([]);
  const [saved, setSaved] = useState<"saved" | "saving" | "">("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const timer = useRef<number>();
  const dirty = useRef(false);

  // Autosave the draft and re-run validation shortly after each change.
  useEffect(() => {
    if (!dirty.current) {
      api(`/tasks/${task.id}/validate`, "POST", { data: clean(values) }).then((r) => { setChecks(r.checks); setSchemaErrors(r.schema_errors); });
      return;
    }
    setSaved("saving");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      await api(`/tasks/${task.id}/draft`, "PUT", { data: values });
      const r = await api(`/tasks/${task.id}/validate`, "POST", { data: clean(values) });
      setChecks(r.checks); setSchemaErrors(r.schema_errors); setSaved("saved");
    }, 600);
    return () => window.clearTimeout(timer.current);
  }, [values, task.id]);

  const change = (id: string, v: any) => { dirty.current = true; setValues((s) => ({ ...s, [id]: v })); };
  const blocking = schemaErrors.length + checks.filter((c) => !c.passed && c.severity === "error").length;
  const submit = async () => {
    try {
      window.clearTimeout(timer.current);
      await api(`/tasks/${task.id}/submit`, "POST", { data: clean(values) });
      onDone();
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && typeof e.detail === "object") {
        setChecks(e.detail.checks ?? []); setSchemaErrors(e.detail.schema_errors ?? []);
        setSubmitError("Fix the problems below before submitting.");
      } else setSubmitError(String((e as Error).message));
    }
  };

  return (
    <>
      {task.status === "failed" && latest?.review && (
        <div className="banner fail">
          <b>Sent back for rework</b> by {latest.review.reviewer}: “{latest.review.comment}”
          <div className="small muted">Your previous submission (v{latest.version}) is loaded below; fix it and resubmit.</div>
        </div>
      )}
      <Split task={task} values={values} onChange={change} readOnly={false}>
        <h4>Automatic checks</h4>
        <ChecksList checks={checks} schemaErrors={schemaErrors} />
        {submitError && <div className="error">{submitError}</div>}
        <div className="actions">
          <button className="primary" onClick={submit} disabled={blocking > 0}>
            {task.status === "failed" ? "Resubmit" : "Submit"} for review
          </button>
          <span className="muted small">{saved === "saving" ? "saving draft…" : saved === "saved" ? "draft saved" : ""}</span>
          {blocking > 0 && <span className="muted small">{blocking} blocking problem(s)</span>}
        </div>
      </Split>
    </>
  );
}

function Inspect({ task, canReview, onDone }: { task: TaskDetail; canReview: boolean; onDone: () => void }) {
  const def = useProject().definition;
  const latest = task.history[task.history.length - 1];
  const [ticks, setTicks] = useState<Record<string, boolean>>({});
  const [comment, setComment] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const values = useMemo(() => latest?.data ?? task.draft ?? {}, [latest, task.draft]);
  const rules = def.review;
  const allTicked = rules.checklist.every((c) => ticks[c]);

  const decide = async (decision: "pass" | "fail") => {
    try {
      await api(`/tasks/${task.id}/review`, "POST", { decision, comment, checklist: ticks });
      onDone();
    } catch (e) { setErr((e as Error).message); }
  };

  if (!latest && !task.draft) {
    return <div className="muted">Nothing submitted yet.</div>;
  }
  return (
    <Split task={task} values={values} onChange={() => {}} readOnly>
      {latest && (
        <>
          <h4>Automatic checks at submit (v{latest.version})</h4>
          <ChecksList checks={latest.checks} />
          {latest.checks.length === 0 && <p className="muted small">No checks configured.</p>}
        </>
      )}
      {canReview && (
        <div className="review-box">
          <h4>Review</h4>
          {rules.checklist.map((c) => (
            <label key={c} className="check-row">
              <input type="checkbox" checked={!!ticks[c]} onChange={(e) => setTicks({ ...ticks, [c]: e.target.checked })} /> {c}
            </label>
          ))}
          <textarea rows={3} placeholder="Comment for the worker (required to fail)" value={comment} onChange={(e) => setComment(e.target.value)} />
          {err && <div className="error">{err}</div>}
          <div className="actions">
            <button className="pass" disabled={rules.require_full_checklist_to_pass && !allTicked} onClick={() => decide("pass")}>✓ Pass</button>
            <button className="fail" disabled={rules.require_comment_on_fail && !comment.trim()} onClick={() => decide("fail")}>✗ Fail → rework</button>
          </div>
          {rules.require_full_checklist_to_pass && !allTicked && <div className="muted small">Tick every checklist item to pass.</div>}
        </div>
      )}
      {!canReview && latest?.review && <ReviewNote v={latest} />}
    </Split>
  );
}
