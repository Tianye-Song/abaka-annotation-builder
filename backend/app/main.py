"""FastAPI entry point: the API, project media, and the built frontend on one port."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from . import db, registry
from .api import router

app = FastAPI(title="Annotation Platform Builder")
app.include_router(router)

FRONTEND_DIST = db.ROOT / "frontend" / "dist"


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/media/{slug}/{path:path}")
def media(slug: str, path: str):
    """Serve item media from the project's own folder (path-traversal safe).

    Not behind mock auth because <audio>/<img> can't send our header; real auth
    would use signed URLs or a session cookie.
    """
    with db.closing() as conn:
        found = registry.get_definition(conn, slug)
    if found is None:
        raise HTTPException(404)
    base = Path(found[0]["source_dir"]).resolve()
    target = (base / path).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    """Single-page app: serve built assets, fall back to index.html for client routes."""
    if full_path.startswith("api/"):
        raise HTTPException(404)
    candidate = (FRONTEND_DIST / full_path).resolve()
    if full_path and candidate.is_relative_to(FRONTEND_DIST.resolve()) and candidate.is_file():
        return FileResponse(candidate)
    index = FRONTEND_DIST / "index.html"
    if not index.exists():
        raise HTTPException(503, "frontend not built: run ./start.sh (or `npm run build` in frontend/)")
    return FileResponse(index)
