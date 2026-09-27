"""Command-line interface for sqliteio."""

from __future__ import annotations

import argparse
import json

from .core import SqliteIO
from .errors import SqliteIOError


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="sqliteio", description="SQLite import/export toolkit")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("tables", help="list all tables")
    p.add_argument("--db", required=True)

    p = sub.add_parser("schema", help="inspect a table")
    p.add_argument("--db", required=True)
    p.add_argument("--table", required=True)

    p = sub.add_parser("export", help="export a table to JSON/CSV")
    p.add_argument("--db", required=True)
    p.add_argument("--table", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--format", default=None, choices=["json", "csv"])
    p.add_argument("--where", default=None)

    p = sub.add_parser("import", help="import JSON/CSV into a table")
    p.add_argument("--db", required=True)
    p.add_argument("--table", required=True)
    p.add_argument("--in", dest="src", required=True)
    p.add_argument("--format", default=None, choices=["json", "csv"])
    p.add_argument("--columns", default=None, help='JSON: {"col":"TYPE"} or ["col",...]')
    p.add_argument("--pk", default=None)
    p.add_argument("--mode", default="replace", choices=["replace", "append", "upsert"])
    p.add_argument("--no-create", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        with SqliteIO(args.db) as io:
            if args.cmd == "tables":
                for t in io.list_tables():
                    print(t)
            elif args.cmd == "schema":
                _print_schema(io, args.table)
            elif args.cmd == "export":
                n = io.export_table(args.table, args.out, args.format, args.where)
                print(f"exported {n} rows -> {args.out}")
            elif args.cmd == "import":
                columns = json.loads(args.columns) if args.columns else None
                n = io.import_table(
                    args.table,
                    args.src,
                    args.format,
                    columns,
                    args.pk,
                    args.mode,
                    create_if_missing=not args.no_create,
                )
                print(f"imported {n} rows -> table {args.table}")
    except SqliteIOError as exc:
        print(f"error: {exc}")
        return 1
    return 0


def _print_schema(io: SqliteIO, table: str) -> None:
    cols = io.get_columns(table)
    if not cols:
        print(f"table not found: {table}")
        return
    for c in cols:
        print(
            f"  {c.name:<24} {c.type:<16} pk={int(c.pk)} notnull={int(c.notnull)} default={c.default}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
