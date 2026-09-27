"""Core :class:`SqliteIO` — schema-agnostic SQLite import/export.

Security notes (ECC hard constraints):
- Table/column identifiers are always double-quoted and inner ``"`` escaped via
  :meth:`SqliteIO._quote_ident`, so identifier values cannot break out of SQL.
- Data values are always passed as bound parameters (never string-interpolated).
- ``where`` is intentionally a raw SQL expression for flexible filtering; it is
  documented as caller-controlled and must only be fed trusted strings.
"""

from __future__ import annotations

import base64
import csv
import json
import os
import sqlite3
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterator, Literal, Mapping, Sequence

from .errors import (
    EmptyDataError,
    TableNotFoundError,
    UnsupportedFormatError,
    ValidationError,
)
from .models import ColumnInfo

Mode = Literal["replace", "append", "upsert"]
Format = Literal["json", "csv"]

_JSON_EXT = (".json",)
_CSV_EXT = (".csv",)


class SqliteIO:
    """A thin, safe facade over a SQLite database for import/export.

    Supports context-manager usage::

        with SqliteIO("data.db") as io:
            io.export_table("nodes", "nodes.json")
    """

    def __init__(self, db_path: str | os.PathLike[str]) -> None:
        self.db_path: str = os.fspath(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    # -- lifecycle ----------------------------------------------------------
    def __enter__(self) -> "SqliteIO":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    # -- introspection ------------------------------------------------------
    def list_tables(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [r["name"] for r in rows]

    def table_exists(self, table: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return row is not None

    def get_columns(self, table: str) -> list[ColumnInfo]:
        self._require_table(table)
        rows = self.conn.execute(f"PRAGMA table_info({self._quote_ident(table)})").fetchall()
        return [
            ColumnInfo(
                name=r["name"],
                type=r["type"] or "TEXT",
                pk=bool(r["pk"]),
                notnull=bool(r["notnull"]),
                default=r["dflt_value"],
            )
            for r in rows
        ]

    def get_primary_key(self, table: str) -> str | None:
        pk_cols = [c.name for c in self.get_columns(table) if c.pk]
        return pk_cols[0] if pk_cols else None

    # -- export -------------------------------------------------------------
    def export_table(
        self,
        table: str,
        output: str | os.PathLike[str],
        fmt: Format | None = None,
        where: str | None = None,
    ) -> int:
        """Export ``table`` to ``output`` (JSON or CSV). Returns row count."""
        self._require_table(table)
        fmt = fmt or self._infer_format(output)
        columns = [c.name for c in self.get_columns(table)]
        rows = [self._row_to_dict(r, columns) for r in self._select_all(table, columns, where)]

        if fmt == "json":
            self._write_json(rows, output)
        else:
            self._write_csv(rows, columns, output)
        return len(rows)

    # -- import -------------------------------------------------------------
    def import_table(
        self,
        table: str,
        source: str | os.PathLike[str],
        fmt: Format | None = None,
        columns: Mapping[str, str] | Sequence[str] | None = None,
        pk: str | None = None,
        mode: Mode = "replace",
        create_if_missing: bool = True,
    ) -> int:
        """Import records from ``source`` (JSON list / CSV) into ``table``.

        ``columns`` is either a ``{name: type-decl}`` mapping or a list of
        names (all ``TEXT``). When omitted and the table exists, the existing
        columns are used; otherwise columns are inferred from the data.
        """
        fmt = fmt or self._infer_format(source)
        records = self._read_records(source, fmt)
        if not records:
            raise EmptyDataError(f"no records found in {source!r}")

        if columns is None and self.table_exists(table):
            columns = [c.name for c in self.get_columns(table)]
        col_defs = self._normalize_columns(columns) if columns else self._infer_columns(records)

        if not self.table_exists(table):
            if not create_if_missing:
                raise TableNotFoundError(table)
            self._create_table(table, col_defs, pk)

        pk = pk or self.get_primary_key(table)
        if mode == "upsert" and not pk:
            raise ValidationError("upsert mode requires a primary key (pk= or an existing PK)")

        target_cols = [c.name for c in self.get_columns(table)]
        keys = [k for k in col_defs if k in target_cols]

        with self.conn:
            if mode == "replace":
                self.conn.execute(f"DELETE FROM {self._quote_ident(table)}")
            for rec in records:
                self._write_record(table, keys, pk, rec, mode)
        self.conn.commit()
        return len(records)

    # -- internal: query / write -------------------------------------------
    def _select_all(
        self, table: str, columns: list[str], where: str | None
    ) -> Iterator[sqlite3.Row]:
        cols = ", ".join(self._quote_ident(c) for c in columns)
        sql = f"SELECT {cols} FROM {self._quote_ident(table)}"
        if where:
            sql += f" WHERE {where}"
        return self.conn.execute(sql).fetchall()

    def _write_record(
        self, table: str, keys: list[str], pk: str | None, rec: Mapping[str, Any], mode: Mode
    ) -> None:
        values = [self._serialize(rec.get(k)) for k in keys]
        if mode == "upsert":
            self.conn.execute(self._upsert_sql(table, keys, pk), values)
        else:
            cols = ", ".join(self._quote_ident(k) for k in keys)
            ph = ", ".join("?" for _ in keys)
            self.conn.execute(
                f"INSERT INTO {self._quote_ident(table)} ({cols}) VALUES ({ph})", values
            )

    def _upsert_sql(self, table: str, keys: list[str], pk: str | None) -> str:
        cols = ", ".join(self._quote_ident(k) for k in keys)
        ph = ", ".join("?" for _ in keys)
        upd = ", ".join(
            f"{self._quote_ident(k)}=excluded.{self._quote_ident(k)}" for k in keys if k != pk
        )
        return (
            f"INSERT INTO {self._quote_ident(table)} ({cols}) VALUES ({ph}) "
            f"ON CONFLICT({self._quote_ident(pk or '')}) DO UPDATE SET {upd}"
        )

    def _create_table(self, table: str, col_defs: Mapping[str, str], pk: str | None) -> None:
        parts = []
        for name, decl in col_defs.items():
            decl = decl or "TEXT"
            if pk and name == pk and "PRIMARY KEY" not in decl.upper():
                decl += " PRIMARY KEY"
            parts.append(f"{self._quote_ident(name)} {decl}")
        self.conn.execute(f"CREATE TABLE {self._quote_ident(table)} ({', '.join(parts)})")

    # -- internal: data source / sink --------------------------------------
    def _read_records(self, source: str | os.PathLike[str], fmt: Format) -> list[dict[str, Any]]:
        path = os.fspath(source)
        if fmt == "json":
            return self._read_json(path)
        return self._read_csv(path)

    @staticmethod
    def _read_json(path: str) -> list[dict[str, Any]]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("rows", data.get("data", [data]))
        if isinstance(data, dict):
            data = [data]
        return data

    @staticmethod
    def _read_csv(path: str) -> list[dict[str, Any]]:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    @staticmethod
    def _write_json(rows: list[dict[str, Any]], path: str | os.PathLike[str]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2, default=str)

    @staticmethod
    def _write_csv(
        rows: list[dict[str, Any]], columns: list[str], path: str | os.PathLike[str]
    ) -> None:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in columns})

    # -- internal: helpers --------------------------------------------------
    def _require_table(self, table: str) -> None:
        if not self.table_exists(table):
            raise TableNotFoundError(table)

    @staticmethod
    def _infer_format(path: str | os.PathLike[str]) -> Format:
        ext = os.path.splitext(os.fspath(path))[1].lower()
        if ext in _JSON_EXT:
            return "json"
        if ext in _CSV_EXT:
            return "csv"
        raise UnsupportedFormatError(ext or "(none)")

    @staticmethod
    def _quote_ident(name: str) -> str:
        """Quote an SQL identifier, escaping inner double quotes (SQL injection safe)."""
        return '"' + name.replace('"', '""') + '"'

    @staticmethod
    def _normalize_columns(columns: Mapping[str, str] | Sequence[str]) -> dict[str, str]:
        if isinstance(columns, Mapping):
            return {k: (v or "TEXT") for k, v in columns.items()}
        if columns and isinstance(columns[0], (list, tuple)):
            return {str(c[0]): str(c[1]) for c in columns}
        return {str(c): "TEXT" for c in columns}

    @staticmethod
    def _infer_columns(records: Sequence[Mapping[str, Any]]) -> dict[str, str]:
        keys: list[str] = []
        for rec in records:
            for k in rec:
                if k not in keys:
                    keys.append(str(k))
        return {k: "TEXT" for k in keys}

    @staticmethod
    def _serialize(val: Any) -> Any:
        if isinstance(val, (bytes, bytearray)):
            return base64.b64encode(bytes(val)).decode("ascii")
        if isinstance(val, (datetime, date, time)):
            return val.isoformat()
        return val

    @staticmethod
    def _row_to_dict(row: sqlite3.Row, columns: list[str]) -> dict[str, Any]:
        return {c: SqliteIO._serialize(row[c]) for c in columns}
