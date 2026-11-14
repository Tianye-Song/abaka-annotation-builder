# Annotation Platform Builder

Create a data-annotation project **from the browser**: write (or copy) a short
definition, upload the data, add the team, and you have a working platform for it.
Each platform has admin, worker and reviewer views, task assignment, a review loop with rework,
validation and quality checks, progress and pass rate, and export. All of that is shared code, so a new project needs no new code.

Three example projects ship with it (audio, image, code). The fourth is created live in the UI.
See **[OVERVIEW.md](OVERVIEW.md)** for the architecture, decisions and trade-offs.

---

## How to launch

**Prerequisites:** Python 3.10+ and Node.js 18+ (`python3 --version`, `node --version`).
[`uv`](https://docs.astral.sh/uv/) is used if it's installed; otherwise the script creates a `venv` with `pip`. Nothing else is needed: storage is a local SQLite file.

**1. Get the code**

```bash
git clone https://github.com/Tianye-Song/abaka-annotation-builder.git   # or unzip the submission
cd abaka-annotation-builder
```

**2. Start it (one command)**

```bash
./start.sh
```

This installs the backend and frontend dependencies, builds the UI and starts the server. The first start also creates
the database with three demo accounts and three example projects. When you see

```
→ open http://localhost:8000  (starts at the login page)
```

**3. Open http://localhost:8000** in a browser. The system starts at the **login page**: choose an account from the
dropdown and enter its password. Three demo accounts are created on first start (defined in [config/seed.yaml](config/seed.yaml)):

| account | password | role | can do |
|---------|----------|------|--------|
| **Alice** | `demo123` | admin | create projects, upload data, manage users and teams, create and assign tasks, see progress, export |
| **Bob** | `demo123` | worker | annotate the tasks assigned to him and submit them |
| **Carol** | `demo123` | reviewer | review Bob's submissions: pass, or fail with a comment |

An account can hold several roles; admins change them on the **Users** page. In every example project Bob is on the team
as a worker and Carol as a reviewer. A sign-in lasts for the browser tab, so you can sign in as a different account in a
second tab side by side; tick **Remember me** to stay signed in across browser restarts. **Sign out** is at the top right.

**Stop** with `Ctrl+C`. **Start over** from a clean slate with `./annotate reset`, then `./start.sh` again.
Use another port with `PORT=8080 ./start.sh`.

**Troubleshooting**
- `database ... uses an old schema` → run `./annotate reset` (the data model changed since the database was created).
- Port already in use → `PORT=8080 ./start.sh`.
- `./start.sh: Permission denied` → `chmod +x start.sh annotate`.

---

## What each role does in the UI

After sign-in, **Your projects** lists every project you can access with your role in each and what's waiting
("3 to do", "2 to review"). Each role tag opens that view directly; **← Projects** brings you back from anywhere.

| Role | Where | What |
|------|-------|------|
| **Admin** | Your projects → **+ New project** | Choose **New project** (blank definition) or **Reuse a previous project**: copy any existing project's definition, optionally reusing its data so nothing needs uploading, or start from an example. The YAML editor checks it as you type and previews the controls, checks and output schema it will generate. Upload data if needed, then **Create**. |
| | your name (top right) → **Users** | Add users (with a password), tick their account roles (any mix of admin / worker / reviewer), reset passwords, delete users who have no work on record. Only users with the worker role can join a team as workers, and only reviewers as reviewers; a role in use on a team can't be removed. |
| | project → **Admin** | Set the project status (active / paused / archived), **Upload items**, **Create tasks**, filter and sort the task list by status, **Assign** tasks (pick a worker and a reviewer independently, or auto-balance either), manage the **Team** (a list of workers and a list of reviewers), see progress, pass rate and first-pass yield, per-worker and per-reviewer progress, and **Export** passed annotations. |
| | Admin → **Definition** | Edit the definition (admins only). Saving creates a new definition version; existing submissions keep the version they were validated against. |
| **Worker** | project → **My tasks** | Rework first (with the reviewer's comment), then to do, then done. Annotate with controls generated from the definition; drafts save automatically and checks run live. **Submit** goes straight to your next task; **← Previous / Next →** steps through your tasks. A submitted task can still be edited and resubmitted until it is reviewed. |
| **Reviewer** | project → **Review** | Only tasks assigned to you for review. Inspect the annotation (read-only), see the automatic check results, tick the checklist, **Pass**, or **Fail** with a comment, which sends the task back to the same worker. |

### How to create a new project instance (no code), then take one task end to end

1. Sign in as **Alice** → **+ New project** → **Reuse a previous project** → *Example definitions*: **Text · LLM answer rubric**. The preview on the right shows what will be generated.
   Under *3 · Data*, choose `examples/llm-rubric/items.jsonl` from this repo → **Create project**.
2. On the new project's **Admin** page: **Team** → add worker **Bob** and reviewer **Carol** → **Create tasks** → tick all → **Assign** (worker and reviewer on auto-balance).
3. *sign out* → sign in as **Bob** → *My tasks* → open a task → score it → **Submit**.
4. *sign out* → sign in as **Carol** → *Review* → open it → write a comment → **Fail → rework**.
5. **Bob** sees it under *Needs rework* with the comment, fixes it → **Resubmit** (v2).
6. **Carol** ticks the checklist → **Pass**. **Alice**'s Admin page now shows the pass rate and first-pass yield, and **Export passed** downloads the JSONL.

More ready-made definitions to try, one per data category (each file's first line says which data to upload):
`examples/call-emotion` (audio), `examples/pedestrian-safety` (image), `examples/review-sentiment` (text).

The same steps work in the audio, image and code projects; only the controls differ. To start from scratch instead,
choose **New project** (blank definition) and see *Writing a definition* below.

---

## Writing a definition

The definition holds only what is unique to the project. Users, team, assignment, review flow and storage are shared.

```yaml
slug: my-project                 # URL id, can't change later
name: "Text · My project"
modality: text                   # the data category: audio | image | text | code
description: ...

data:                            # how uploaded data becomes items
  kind: jsonl                    # jsonl: one item per line (needs "id"); other keys become item metadata
  path: items.jsonl              # files: one item per uploaded media file matching `glob`
  # glob: "*.wav"                #   (audio duration / PNG size are probed automatically)

display:                         # which item metadata to show, and how (text | code | markdown)
  - {key: question, label: Question}

task:
  instructions: Markdown shown to workers and reviewers.
  fields:                        # the worker's controls, in order
    - {id: verdict, type: choice, choices: [yes, no], required: true}
    - {id: why, type: text, multiline: true, required_when: {field: verdict, equals: no}}
  checks:                        # automatic QC: "error" blocks submit, "warning" informs the reviewer
    - {check: min_words, field: why, min: 5}

review:
  checklist: [The verdict is right]   # the reviewer must tick every item to pass (configurable)
  require_comment_on_fail: true
```

| field type       | params                                   | modalities | saved value |
|------------------|------------------------------------------|------------|-------------|
| `choice`         | `choices`, `multiple`                    | all        | `"a"` or `["a","b"]` |
| `text`           | `multiline`, `placeholder`               | all        | `"..."` |
| `rating`         | `min`, `max`, `labels`                   | all        | `4` |
| `bbox`           | `classes`                                | image      | `[{x,y,w,h,label}]` (natural pixels) |
| `audio_segments` | `speakers`, `transcribe`                 | audio      | `[{start,end,speaker,text}]` (seconds) |

| check             | params      | applies to |
|-------------------|-------------|------------|
| `min_count`       | `min`       | bbox, audio_segments, choice(multiple) |
| `min_words`       | `min`       | text |
| `no_overlap`      | –           | audio_segments |
| `within_duration` | –           | audio_segments |
| `coverage`        | `min_ratio` | audio_segments |
| `within_image`    | –           | bbox |
| `min_box_size`    | `min_px`    | bbox |

Every field also accepts `label`, `help`, `required` and `required_when`.
Mistakes such as an unknown field type, a `bbox` on an audio project, or a check on a missing field are shown in the editor before anything is created.

**Same data category, new project:** in **New project** choose **Reuse a previous project**, pick a project already in the system, and keep *Also reuse its data* ticked to label the same items differently, or untick it and upload new data. The slug is renamed automatically (`…-v2`); change labels or fields as needed.
**New data category or control:** add one field type in `backend/app/fields.py` and one widget in `frontend/src/fields/`. This is the only case that needs code.

---

## Data model (SQLite, `backend/app/db.py`)

| table | your entity | columns (key ones) |
|-------|-------------|--------------------|
| `users` | **user** | `id`, `name`, `password_hash` (salted PBKDF2) |
| `user_roles` | account roles | `user_id`, `role`: admin (create projects, manage users and teams), worker (can be assigned jobs), reviewer (can review); a user may hold several |
| `sessions` | *(added)* login sessions | `token` (sent as `Authorization: Bearer …`), `user_id`, `created_at` |
| `projects` | **tasks** (schema, job list, status) | `id`, `slug`, `name`, `modality` (= task category), `status` (active/paused/archived), `definition_yaml` + `definition` (= schema), `created_by`, `created_at` |
| `project_members` | **team** | `project_id`, `user_id`, `role` (worker or reviewer, independent), `created_by`, `created_at` |
| `tasks` | **jobs** | `id`, `project_id`, `item_id`, `status`, `assignee` (worker), `reviewer_id` (chosen when the task is assigned), `draft` |
| `items` | *(added)* the data behind each job | `external_id`, `payload` (media path + metadata) |
| `submissions` | *(added)* what the worker produced | `task_id`, `version`, `data` (validated against the schema), `check_results`, `definition_hash` |
| `reviews` | *(added)* the reviewer's decision | `submission_id`, `reviewer_id`, `decision` (pass/fail), `comment`, `checklist` |
| `project_roles` (view) | – | derived `(project, user, role)`: account admins and the creator + the project's workers and reviewers; the portal lists these with a link to each role's view |

A job's lifecycle: `unassigned → assigned → submitted → passed`. `submitted → failed` sends it back to the same worker, and resubmitting creates v2 (`failed → submitted`).
Until the reviewer decides, the worker may edit a submitted job; that replaces the pending submission instead of adding a version.

---

## Development

```bash
cd backend && uv run pytest -q                                  # end-to-end API tests (the same calls the UI makes)
cd backend && uv run uvicorn app.main:app --reload --port 8000  # API with reload
cd frontend && npm run dev                                      # UI with HMR on :5173 (proxies /api to :8000)
./annotate reset                                                # dev only: wipe the DB + uploads; next start re-seeds
```

```
backend/app/
  definition.py  definition models, cross-validation, output-schema derivation
  fields.py      field-type registry (params, modality, JSON Schema)
  checks.py      automatic quality-check registry
  lifecycle.py   task state machine (who can move a task where)
  registry.py    create/update a project from YAML + uploads; first-run seed
  api.py         every operation the UI performs
  db.py          SQLite schema
frontend/src/
  fields/        widget registry: one widget per field type
  components/    DefinitionEditor (live-validated YAML), shared views
  pages/         Portal (+login), NewProject, Users, Admin (+Team), Queues, TaskPage, Definition
projects/        example projects seeded on first start (definition + sample data)
examples/        more definitions (+ data) to create new projects from in the UI
config/seed.yaml first-run users and teams
```
