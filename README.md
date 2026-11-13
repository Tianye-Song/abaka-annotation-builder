# Annotation Platform Builder

Describe an annotation project in one YAML file and get a working platform for it:
admin, worker and reviewer views, task assignment, a review loop with rework,
validation and quality checks, progress and pass rate, and export.

This repo includes three projects built that way (audio, image and code) and a
fourth that you can stand up live with one command.

See **[OVERVIEW.md](OVERVIEW.md)** for the architecture, design decisions and trade-offs.

---

## Setup and run (one command)

Requirements: Python ≥ 3.10, Node ≥ 18. [`uv`](https://docs.astral.sh/uv/) is used if installed; otherwise the script falls back to `venv` + `pip`.

```bash
./start.sh
```

The script installs dependencies, builds the UI, registers every project under
`projects/`, and serves the app at **http://localhost:8000**.

Sign in by picking a user. Login is mocked; the picker shows each user's role in each project.

| user  | speaker-turns (audio) | street-objects (image) | code-correctness (code) |
|-------|-----------------------|------------------------|-------------------------|
| alice | admin                 | admin                  | admin                   |
| bob   | worker                | **reviewer**           | –                       |
| carol | worker                | worker                 | **reviewer**            |
| dan   | **reviewer**          | worker                 | worker                  |
| erin  | –                     | –                      | worker                  |

To start over with a clean database: `./annotate reset`.

### Walk one task through the lifecycle (image project)

1. **alice** → *Image · Street objects* → **Admin**: *Create tasks* → tick the header checkbox → *Assign selected*.
   The default assignment spreads tasks across workers, giving each new task to the worker with the fewest open tasks.
2. **carol** → **My tasks** → open a task, pick a class and drag boxes on the image.
   The automatic checks run as you work, and the draft saves itself. Then *Submit for review*.
3. **bob** → **Review**: open the task. He sees the boxes read-only, the check results and the checklist.
   Writing a comment and clicking *Fail → rework* sends the task back.
4. **carol** sees the task under *Needs rework* with bob's comment. Her previous boxes are preloaded; she fixes them and clicks *Resubmit* (this creates v2).
5. **bob** ticks the checklist and clicks *Pass*. **alice**'s dashboard now shows the pass rate, first-pass yield and the per-worker table, and *Export passed (JSONL)* downloads the result.

The same steps work in the audio and code projects with the same people in different roles.

---

## Creating a new project instance

A project is a folder with a `project.yaml` and its data. **No code changes are needed.**

```bash
./annotate validate examples/llm-rubric   # optional: check the definition and data, touches nothing
./annotate create   examples/llm-rubric   # register it, its members and its items
```

Reload the browser: **erin** is now admin of *Text · LLM answer rubric*, bob is a worker and dan is the reviewer.
The `create` command also works on a running server. It is idempotent: run it again after editing the YAML to update the definition and members and to load any new items.

Other commands:

```bash
./annotate schema projects/code-correctness   # print the output JSON Schema derived from the definition
./annotate init                               # create/update every project under projects/
```

### Definition reference

```yaml
slug: my-project                 # URL id
name: "Text · My project"
modality: text                   # audio | image | text
description: ...

data:                            # how items are loaded
  kind: jsonl                    # jsonl: one item per line, needs "id"; other keys become item metadata
  path: items.jsonl              # files: one item per file matching `glob` under `path`
  # glob: "*.wav"                #   (audio duration / PNG size are probed automatically)
  # meta: meta.jsonl             #   optional per-file metadata: {"file": "a.wav", ...}

display:                         # which item metadata to show, and how (text | code | markdown)
  - {key: question, label: Question}

task:
  instructions: Markdown shown to workers and reviewers.
  fields:                        # the worker's controls; the order here is the order on screen
    - {id: verdict, type: choice, choices: [yes, no], required: true}
    - {id: why, type: text, multiline: true, required_when: {field: verdict, equals: no}}
  checks:                        # automatic quality checks; "error" blocks submit, "warning" informs the reviewer
    - {check: min_words, field: why, min: 5}

review:
  checklist: [The verdict is right]   # the reviewer must tick every item to pass (configurable)
  require_comment_on_fail: true

members: {alice: admin, bob: worker, carol: [reviewer, worker]}
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
A definition is fully validated before anything is written. Errors include unknown field types, a `bbox` field on an audio project, a check that refers to a missing field, and a bad parameter.

### Adding a new *kind* of control (rare)

Add the backend type to `backend/app/fields.py` (its params and JSON Schema) and the widget to `frontend/src/fields/` (one React component plus a registry entry).
Every project can then use it from YAML.

---

## How each example was created

| project | definition | data | command | what I did *not* have to write |
|---|---|---|---|---|
| Audio · Speaker turns | [projects/speaker-turns/project.yaml](projects/speaker-turns/project.yaml) | 6 synthetic 2-speaker dialogues (macOS TTS) | `./annotate create projects/speaker-turns` | audio player and timeline UI, segment validation, overlap/duration checks, review screen, workflow |
| Image · Street objects | [projects/street-objects/project.yaml](projects/street-objects/project.yaml) | 7 generated street scenes (Pillow) | `./annotate create projects/street-objects` | box drawing UI, coordinate schema, in-bounds/min-size checks, review screen, workflow |
| Code · Correct or buggy | [projects/code-correctness/project.yaml](projects/code-correctness/project.yaml) | 8 Python snippets (4 buggy) | `./annotate create projects/code-correctness` | code display, the conditional "category required if buggy" rule, rating widget, workflow |
| Text · LLM rubric (4th) | [examples/llm-rubric/project.yaml](examples/llm-rubric/project.yaml) | 5 Q/A pairs | `./annotate create examples/llm-rubric` | everything. It's ~30 lines of YAML |

All sample data is synthetic. `scripts/make_samples.py` regenerates the audio and images.
In the app, each project's **Definition** tab shows the YAML next to what the platform derived from it, including the output JSON Schema.

---

## Development

```bash
cd backend && uv run pytest -q                                  # end-to-end lifecycle tests for all 4 projects
cd backend && uv run uvicorn app.main:app --reload --port 8000  # API with reload
cd frontend && npm run dev                                      # UI with HMR on :5173 (proxies /api to :8000)
```

```
backend/app/
  definition.py  project definition models, cross-validation, output-schema derivation
  fields.py      field-type registry (params, modality, JSON Schema)
  checks.py      automatic quality-check registry
  lifecycle.py   task state machine (who can move a task where)
  registry.py    definition folder -> project instance (members, item loading, media probing)
  api.py         shared HTTP API for every project (admin / worker / reviewer)
  db.py          SQLite schema
  cli.py         ./annotate commands
frontend/src/
  fields/        widget registry, one widget per field type
  pages/         Portal, Admin, Queues, TaskPage (annotate / review / view), Definition
projects/        the three example projects (definition + data)
examples/        the "fourth project"
```
