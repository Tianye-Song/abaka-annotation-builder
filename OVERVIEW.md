# Annotation Platform Builder: one-page overview

## Architecture

```
projects/<slug>/project.yaml  ──./annotate create──►  validate ─► register project, members, items (SQLite)
          + data/                                                  │
                                                                   ▼
               one FastAPI service + one React app, shared by every project
     ┌──────────────────────────────────────────────────────────────────────────────┐
     │ shared core: users/roles · assignment · lifecycle · review · storage · stats │
     │ registries:  field types (backend schema ⇄ frontend widget) · quality checks │
     └──────────────────────────────────────────────────────────────────────────────┘
          /p/<slug>/admin     /p/<slug>/work     /p/<slug>/review     /  (portal)
```

**The mechanism is interpretation, not code generation.** A project is data: a validated
definition stored with the project row. The single runtime reads it to decide how items load,
which controls the worker gets, what a valid annotation is, which checks run and what the
reviewer must confirm. A "platform instance" is a project row plus its definition. All instances
share one process, one database and one UI bundle, and each has its own URL namespace, members and data.

**How a definition becomes a platform**
1. **Validate**: Pydantic models check the YAML. Cross-field rules are checked too: the field type
   must suit the modality, checks must refer to existing fields of a compatible type, and `required_when` targets must exist.
   Bad definitions fail loudly before anything is written.
2. **Derive**: each field type contributes a JSON Schema fragment. Together they form the project's
   **output schema** (including conditional rules such as "bug_category is required when verdict = buggy").
   The server enforces that schema on submit. It is also shown on the Definition tab and works as the delivery contract.
3. **Register**: upsert the project, replace its members (the YAML is the source of truth) and import items
   idempotently. Cheap media probing (WAV duration, PNG size) feeds the checks.
4. **Render**: the frontend looks up each field's `type` in a widget registry. "Surface" widgets
   (`bbox`, `audio_segments`) own the media, because you draw on the image and mark time on the audio. Others sit in the side panel.
   The same widget runs in read-only mode for reviewers, so the reviewer sees exactly what the worker produced.

**The fourth-project test.** `examples/llm-rubric` is about 30 lines of YAML and needs no code: `./annotate create examples/llm-rubric`.
New code is only needed for a genuinely new *kind* of control (polygon, keypoints, NER spans). That is one backend class
plus one React component, and every project can then use it.

## Key design decisions and trade-offs

| Decision | Why | Cost |
|---|---|---|
| Interpret at runtime (no codegen) | Fixes to the shared core reach every project at once, there are no forked apps, and a definition update is just a DB write | Per-project custom UI is limited to the widget library; an escape hatch (custom widget plug-ins) is future work |
| YAML + Pydantic, not a builder UI | Diffable, reviewable in PRs, fast to write, gives precise errors | Less friendly to non-engineers; a builder UI could emit the same YAML later |
| Relational workflow, JSON payloads | Status, assignee and reviews are columns, so the same SQL serves every project; project-specific shape stays in JSON validated by JSON Schema | Can't index or query inside annotations without JSON1 or Postgres JSONB |
| Explicit state machine (`lifecycle.py`) | One table says which role may make which move. Rework keeps the assignee, so a failed task always returns to the same worker with the comment | One task per item; consensus or multi-annotator overlap needs a task-per-(item, annotator) model |
| Every submission is immutable and versioned, stamped with the definition hash | Full rework history, first-pass yield, and audit of which schema an annotation was checked against | Changing a definition mid-project doesn't migrate old annotations; they are flagged by hash only |
| Two-tier QC: schema + `error` checks block submit; `warning` checks inform the reviewer | Workers fix mechanical mistakes before a human ever looks; reviewers spend time on judgement | Checks are Python functions, so a new check type needs code, though wiring one up is pure YAML |
| Reviewer checklist from the definition | Makes review criteria explicit and consistent; `pass` requires ticking all items (configurable) | Checklist answers are stored but not yet scored or analysed |
| Mock auth via an `X-User` header; per-project roles | The task allowed it; roles are per project, which made the **unified portal** almost free (built) | No real security; media URLs are unauthenticated (real version: session cookie + signed URLs) |

**Unified portal (optional item, built):** one login lists every project you belong to, your role or roles in each,
and what is waiting for you ("3 to do · 1 rework", "2 to review"). Each role links straight to the right view.

## What breaks at scale, and what I'd change first

- **50 projects:** the code is fine; the operational gaps are the problem. Definitions need versioning with migrations,
  per-project permissions managed outside YAML, and a project-creation UI. Each project's data folder sits on local disk, so it should move to object storage (S3/GCS) with signed URLs.
- **10,000 tasks:** SQLite with indexes copes with reads, but the admin overview returns every row and uses correlated
  subqueries. **First changes:** paginate and filter the admin table, keep denormalised counters per project,
  move to Postgres (JSONB for annotations, row-level locking), and add a "pull next task" queue
  (`SELECT … FOR UPDATE SKIP LOCKED`) instead of admin-pushed assignment so workers never collide.

## What I cut (scope) and what I'd build next

Cut: real auth, file upload through the UI (admins drop files into the data folder and press *Load items*),
multi-annotator overlap and agreement metrics, reviewer assignment and sampling, gold questions, keyboard shortcuts,
a waveform display, text-span (NER) and polygon widgets.

Next, in order: (1) **consensus and gold tasks** (task per item×annotator, agreement and accuracy per worker);
(2) **review sampling** (review x% of trusted workers' output, 100% of new workers');
(3) **definition versioning** with migrations and a diff view;
(4) more field types (text spans, polygons, keypoints, pairwise comparison) and a plug-in path for one-off custom widgets;
(5) a definition builder UI that writes the same YAML, with a live preview of the worker screen.

## Assumptions

- One task per item, and one worker per task. "Create tasks" makes one task for each item that has none.
- Reviewers draw from a shared queue and cannot review their own work.
- "Pass rate" counts passed reviews among all reviews. "First-pass yield" is the share of v1 submissions that passed.
- All sample data is synthetic: TTS audio, drawn images, and hand-written code snippets and Q/A pairs.
