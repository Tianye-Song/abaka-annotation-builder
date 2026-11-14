#!/usr/bin/env bash
# One command: install deps, build the UI, serve on :8000.
# First start seeds example users and projects; everything else happens in the UI.
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
  .venv/bin/pip install --quiet fastapi uvicorn pydantic pyyaml jsonschema python-multipart
  PY=(.venv/bin/python)
fi

echo "→ frontend build"
cd "$ROOT/frontend"
[ -d node_modules ] || npm install --no-audit --no-fund --silent
npm run --silent build >/dev/null

cd "$ROOT/backend"
echo "→ open http://localhost:$PORT  (starts at the login page)"
exec "${PY[@]}" -m uvicorn app.main:app --port "$PORT"
