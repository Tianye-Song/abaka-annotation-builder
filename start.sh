#!/usr/bin/env bash
# One command: install deps, build the UI, create the example projects, serve on :8000.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-8000}"

echo "→ backend deps"
cd "$ROOT/backend"
if command -v uv >/dev/null 2>&1; then
  uv sync --quiet
  PY=(uv run --quiet python)
else
  [ -d .venv ] || python3 -m venv .venv
  .venv/bin/pip install --quiet fastapi uvicorn pydantic pyyaml jsonschema
  PY=(.venv/bin/python)
fi

echo "→ frontend build"
cd "$ROOT/frontend"
[ -d node_modules ] || npm install --no-audit --no-fund --silent
npm run --silent build >/dev/null

echo "→ projects"
cd "$ROOT/backend"
"${PY[@]}" -m app.cli init

echo "→ http://localhost:$PORT"
exec "${PY[@]}" -m uvicorn app.main:app --port "$PORT"
