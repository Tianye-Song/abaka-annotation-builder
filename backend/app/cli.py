"""Developer maintenance only. Every user-facing operation happens in the UI.

    python -m app.cli reset    # delete the database and uploaded data; the next start re-seeds
"""
from __future__ import annotations

import shutil
import sys

from pathlib import Path

from . import db, registry


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["reset"]:
        print(__doc__)
        return 1
    for suffix in ("", "-wal", "-shm"):
        Path(f"{db.DB_PATH}{suffix}").unlink(missing_ok=True)
    shutil.rmtree(registry.PROJECTS_HOME, ignore_errors=True)
    print(f"deleted {db.DB_PATH} and {registry.PROJECTS_HOME} - restart (./start.sh) to re-seed the examples")
    return 0


if __name__ == "__main__":
    sys.exit(main())
