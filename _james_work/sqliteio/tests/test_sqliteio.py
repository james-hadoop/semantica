"""Unit tests for sqliteio (pytest).

Run: pytest -q
"""

from __future__ import annotations

import base64
import json
from datetime import date

import pytest

from sqliteio import (
    ApiResponse,
    EmptyDataError,
    SqliteIO,
    TableNotFoundError,
    UnsupportedFormatError,
    ValidationError,
)


@pytest.fixture
def io(tmp_path):
    with SqliteIO(tmp_path / "test.db") as instance:
        yield instance


@pytest.fixture
def populated(io):
    """A nodes table with three rows (id TEXT PRIMARY KEY)."""
    io.import_table(
        "nodes",
        _tmp_json(
            [
                {"id": "a", "type": "Paper", "label": "Paper A"},
                {"id": "b", "type": "Author", "label": "Alice"},
                {"id": "c", "type": "Author", "label": "Bob"},
            ]
        ),
        columns={"id": "TEXT PRIMARY KEY", "type": "TEXT", "label": "TEXT"},
        mode="replace",
    )
    return io


def _tmp_json(rows):
    import tempfile
    import os

    p = os.path.join(tempfile.gettempdir(), "sqliteio_test.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rows, f)
    return p


# ---- introspection --------------------------------------------------------
def test_list_tables_empty(io):
    assert io.list_tables() == []


def test_table_exists_and_columns(populated):
    assert populated.table_exists("nodes")
    cols = populated.get_columns("nodes")
    assert [c.name for c in cols] == ["id", "type", "label"]
    assert cols[0].pk is True
    assert populated.get_primary_key("nodes") == "id"


# ---- export ---------------------------------------------------------------
def test_export_json_roundtrip(populated, tmp_path):
    out = tmp_path / "nodes.json"
    n = populated.export_table("nodes", out)
    assert n == 3
    data = json.loads(out.read_text(encoding="utf-8"))
    assert {r["id"] for r in data} == {"a", "b", "c"}


def test_export_csv_with_where(populated, tmp_path):
    out = tmp_path / "authors.csv"
    n = populated.export_table("nodes", out, where="type='Author'")
    assert n == 2


def test_export_missing_table_raises(io, tmp_path):
    with pytest.raises(TableNotFoundError):
        io.export_table("nope", tmp_path / "x.json")


def test_export_unsupported_format(populated, tmp_path):
    with pytest.raises(UnsupportedFormatError):
        populated.export_table("nodes", tmp_path / "x.parquet")


# ---- import ---------------------------------------------------------------
def test_import_replace_truncates(populated):
    n = populated.import_table(
        "nodes", _tmp_json([{"id": "z", "type": "Paper", "label": "Z"}]), mode="replace"
    )
    assert n == 1
    cnt = populated.conn.execute("SELECT COUNT(*) c FROM nodes").fetchone()["c"]
    assert cnt == 1  # 原有 3 行被清空重建


def test_import_append_adds(populated):
    populated.import_table(
        "nodes", _tmp_json([{"id": "d", "type": "Paper", "label": "D"}]), mode="append"
    )
    cnt = populated.conn.execute("SELECT COUNT(*) c FROM nodes").fetchone()["c"]
    assert cnt == 4


def test_import_upsert_updates_by_pk(populated):
    populated.import_table(
        "nodes",
        _tmp_json([{"id": "a", "type": "Paper", "label": "Updated"}]),
        mode="upsert",
        pk="id",
    )
    row = populated.conn.execute("SELECT label FROM nodes WHERE id='a'").fetchone()
    assert row["label"] == "Updated"
    cnt = populated.conn.execute("SELECT COUNT(*) c FROM nodes").fetchone()["c"]
    assert cnt == 3  # updated, not duplicated


def test_import_upsert_without_pk_raises(io):
    with pytest.raises(ValidationError):
        io.import_table("t", _tmp_json([{"x": 1}]), columns={"x": "TEXT"}, mode="upsert")


def test_import_empty_raises(io):
    with pytest.raises(EmptyDataError):
        io.import_table("t", _tmp_json([]), columns={"x": "TEXT"})


def test_import_auto_create(io):
    n = io.import_table("words", _tmp_json([{"w": "hi"}]), columns={"w": "TEXT"})
    assert n == 1
    assert io.table_exists("words")


# ---- security: identifier quoting -----------------------------------------
def test_identifier_injection_is_quoted(io):
    """A malicious column name must be treated as a literal identifier, not SQL."""
    evil = 'x"; DROP TABLE nodes; --'
    io.import_table("safe", _tmp_json([{evil: "v"}]), columns={evil: "TEXT"})
    # 恶意列名被 _quote_ident 整体转义为一个字面标识符，未破坏 SQL、未执行 DROP
    assert io.table_exists("safe")
    cols = [c.name for c in io.get_columns("safe")]
    assert evil in cols


# ---- serialization ---------------------------------------------------------
def test_serialize_bytes_and_date(io):
    raw = base64.b64encode(b"hello").decode()
    payload = [{"id": "1", "blob": raw, "day": "2026-01-01"}]
    io.import_table(
        "ser", _tmp_json(payload), columns={"id": "TEXT", "blob": "TEXT", "day": "TEXT"}
    )
    row = io.conn.execute("SELECT * FROM ser WHERE id='1'").fetchone()
    assert row["day"] == "2026-01-01"


# ---- models ----------------------------------------------------------------
def test_api_response_envelope():
    ok = ApiResponse.ok(data={"rows": 3}, meta={"total": 3})
    assert ok.success and ok.error is None and ok.meta["total"] == 3
    fail = ApiResponse.fail(error="boom")
    assert not fail.success and fail.data is None
