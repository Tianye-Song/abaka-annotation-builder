import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, apiForm, problemsOf, useLoad, type Derived } from "../api";
import { DefinitionEditor } from "../components/DefinitionEditor";
import { MODALITY_ICON as ICON, ProblemList } from "../components/common";

interface ExistingProject { slug: string; name: string; modality: string; yaml: string; items: number; created_by: string | null }
interface Example { slug: string; name: string; modality: string; yaml: string; sample_data: string | null }
interface Sources { projects: ExistingProject[]; examples: Example[] }

const BLANK = `slug: my-project
name: "Text · My project"
modality: text            # audio | image | text | code
description: What annotators do here.

data:
  kind: jsonl             # jsonl: one item per line (needs "id") | files: one item per media file
  path: items.jsonl
  # glob: "*.wav"         # for kind: files

display:
  - {key: text, label: Passage}

task:
  instructions: Read the passage and label it.
  fields:
    - {id: label, type: choice, label: Label, choices: [positive, negative], required: true}
    - {id: note, type: text, label: Note}

review:
  checklist: [Label is correct]
`;

/** A slug that doesn't exist yet: street-objects -> street-objects-v2 (-v3, ...). */
function nextSlug(slug: string, taken: Set<string>): string {
  const base = slug.replace(/-v\d+$/, "");
  for (let n = 2; ; n++) if (!taken.has(`${base}-v${n}`)) return `${base}-v${n}`;
}

/** Admin: start a project as new (blank) or by reusing a previous project or an example. No code. */
export function NewProject() {
  const nav = useNavigate();
  const { data: sources } = useLoad(() => api<Sources>("/templates"), []);
  const [mode, setMode] = useState<"new" | "reuse">("new");
  const [source, setSource] = useState(""); // "p:<slug>" (existing project) or "e:<slug>" (example)
  const [reuseData, setReuseData] = useState(true);
  const [yaml, setYaml] = useState(BLANK);
  const [derived, setDerived] = useState<Derived | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [params] = useSearchParams();

  // "Use as template" from a project's Admin page: /new-project?from=<slug> preselects reuse.
  useEffect(() => {
    const from = params.get("from");
    if (from && sources?.projects.some((p) => p.slug === from)) {
      setMode("reuse");
      pick(`p:${from}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sources]);

  const taken = new Set(sources?.projects.map((p) => p.slug) ?? []);
  const existing = source.startsWith("p:") ? sources?.projects.find((p) => p.slug === source.slice(2)) : undefined;
  const example = source.startsWith("e:") ? sources?.examples.find((e) => e.slug === source.slice(2)) : undefined;
  const copyingData = !!existing && reuseData;

  const chooseMode = (m: "new" | "reuse") => {
    setMode(m);
    setSource("");
    setYaml(BLANK);
  };
  const pick = (value: string) => {
    setSource(value);
    const src = value.startsWith("p:") ? sources?.projects.find((p) => p.slug === value.slice(2))
      : sources?.examples.find((e) => e.slug === value.slice(2));
    if (!src) return setYaml(BLANK);
    // Same definition under a new slug; edit labels/fields as needed below.
    const slug = taken.has(src.slug) ? nextSlug(src.slug, taken) : src.slug;
    setYaml(src.yaml.replace(/^slug: .*$/m, `slug: ${slug}`));
  };

  const create = async () => {
    setBusy(true);
    setProblems([]);
    const form = new FormData();
    form.append("definition", yaml);
    if (copyingData) form.append("copy_data_from", existing!.slug);
    files.forEach((f) => form.append("files", f));
    try {
      const r = await apiForm<{ slug: string }>("/projects", form);
      nav(`/p/${r.slug}/admin`);
    } catch (e) {
      setProblems(problemsOf(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <Link to="/" className="button-like back-to-projects">← Projects</Link>
      <h1>New project</h1>
      <div className="steps">
        <section>
          <h3>1 · How do you want to start?</h3>
          <div className="start-options">
            <label className={`start-option ${mode === "new" ? "on" : ""}`}>
              <input type="radio" checked={mode === "new"} onChange={() => chooseMode("new")} />
              <div><b>New project</b><div className="muted small">Start from a blank definition.</div></div>
            </label>
            <label className={`start-option ${mode === "reuse" ? "on" : ""}`}>
              <input type="radio" checked={mode === "reuse"} onChange={() => chooseMode("reuse")} />
              <div><b>Reuse a previous project</b><div className="muted small">Copy an existing project's definition (and optionally its data), then adjust it.</div></div>
            </label>
          </div>
          {mode === "reuse" && (
            <div className="reuse-pick">
              <select value={source} onChange={(e) => pick(e.target.value)}>
                <option value="" disabled>Choose a project to reuse…</option>
                <optgroup label="Projects in the system">
                  {sources?.projects.map((p) => (
                    <option key={p.slug} value={`p:${p.slug}`}>{ICON[p.modality]} {p.name} — {p.items} items</option>
                  ))}
                </optgroup>
                <optgroup label="Example definitions">
                  {sources?.examples.map((e) => (
                    <option key={e.slug} value={`e:${e.slug}`}>{ICON[e.modality]} {e.name}</option>
                  ))}
                </optgroup>
              </select>
              {existing && (
                <label className="check-row">
                  <input type="checkbox" checked={reuseData} onChange={(e) => setReuseData(e.target.checked)} />
                  Also reuse its data ({existing.items} items), so no upload is needed
                </label>
              )}
            </div>
          )}
        </section>

        {(mode === "new" || source) && (
          <>
            <section>
              <h3>2 · Define it</h3>
              <p className="muted small">
                {mode === "reuse" ? "This is a copy with a new slug. Rename it and change the labels, fields or checks as needed." : "Describe the data, the worker's controls, the checks and the review rules."}
              </p>
              <DefinitionEditor value={yaml} onChange={setYaml} onValid={setDerived} />
            </section>

            <section>
              <h3>3 · Data</h3>
              {copyingData && <div className="flash">Reusing the {existing!.items} items of <b>{existing!.name}</b>. You can add more files below.</div>}
              <input type="file" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
              <div className="muted small">
                {derived
                  ? derived.data.kind === "files"
                    ? <>Media files matching <code>{derived.data.glob}</code>.</>
                    : <>A <code>.jsonl</code> file with one item per line.</>
                  : "Fix the definition first."}
                {example?.sample_data && <> Sample data: <code>{example.sample_data}/</code> in the repo.</>}
                {example && !example.sample_data && <> The template's first comment line says where its sample data is.</>}
                {" "}You can also upload more later from the Admin page.
              </div>
              {files.length > 0 && <div className="small">{files.length} file(s) selected</div>}
            </section>

            <section>
              <h3>4 · Create</h3>
              {problems.length > 0 && <ProblemList problems={problems} />}
              <button className="primary" disabled={!derived || busy} onClick={create}>
                {busy ? "Creating…" : `Create project${derived ? ` “${derived.name}”` : ""}`}
              </button>
              <span className="muted small"> Next, add the team (workers and reviewers) on the Admin page.</span>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
