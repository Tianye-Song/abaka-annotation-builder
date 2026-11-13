"""Command line for operators.

    python -m app.cli create ../projects/<slug>    # stand up / update one project
    python -m app.cli validate ../projects/<slug>  # check a definition without touching the DB
    python -m app.cli schema ../projects/<slug>    # print the derived output JSON Schema
    python -m app.cli init                         # create every project under projects/
    python -m app.cli reset                        # delete the database, then init
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from . import db, registry
from .definition import load_definition, output_schema


def _print_result(r: dict) -> None:
    print(f"✓ {r['slug']}: definition {r['action']} ({r['hash']}), "
          f"{r['items_added']} new items ({r['items_total']} total)")
    for u, role in r["members"]:
        print(f"    {role:<9} {u}")
    if r["new_users"]:
        print(f"    (created users: {', '.join(r['new_users'])})")
    print(f"    open: http://localhost:8000/p/{r['slug']}")


def _create(path: Path) -> bool:
    try:
        _print_result(registry.create_project(path))
        return True
    except ValidationError as e:
        print(f"✗ {path}: invalid definition", file=sys.stderr)
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            print(f"    {loc}: {err['msg']}", file=sys.stderr)
    except (OSError, ValueError) as e:
        print(f"✗ {path}: {e}", file=sys.stderr)
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="annotate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("create", "validate", "schema"):
        sub.add_parser(name).add_argument("project_dir", type=Path)
    sub.add_parser("init")
    sub.add_parser("reset")
    args = ap.parse_args(argv)

    if args.cmd == "create":
        return 0 if _create(args.project_dir) else 1
    if args.cmd == "validate":
        try:
            d = load_definition(args.project_dir)
            n = len(registry.read_items(d, args.project_dir.resolve()))
            print(f"✓ {d.slug}: valid ({d.modality}, {len(d.task.fields)} fields, "
                  f"{len(d.task.checks)} checks, {n} items found)")
            return 0
        except ValidationError as e:
            for err in e.errors():
                print(f"✗ {'.'.join(map(str, err['loc']))}: {err['msg']}", file=sys.stderr)
            return 1
    if args.cmd == "schema":
        print(json.dumps(output_schema(load_definition(args.project_dir)), indent=2))
        return 0
    if args.cmd == "reset" and db.DB_PATH.exists():
        for suffix in ("", "-wal", "-shm"):
            Path(str(db.DB_PATH) + suffix).unlink(missing_ok=True)
        print(f"deleted {db.DB_PATH}")
    # init / reset
    ok = all([_create(p) for p in registry.discover()])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
