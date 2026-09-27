# -*- coding: utf-8 -*-
"""通用 SQLite 数据导入 / 导出工具。

设计目标：不依赖任何特定 schema，通过「指定库、表、字段、主键」等必要信息，
即可对任意 SQLite 表做导入 / 导出，可复用到任何场景。

特性：
  - 导出：任意表 -> JSON / CSV（自动识别列，支持 WHERE 过滤，BLOB/日期安全序列化）
  - 导入：JSON / CSV -> 任意表（支持 replace / append / upsert 三种模式）
  - 建表：表不存在时可依据字段定义自动建表
  - 元信息：列出所有表、查看表结构
  - 既可作为命令行工具，也可 import 为库函数使用

命令行用法：
  # 1) 列出数据库所有表
  python sqlite_io_tool.py tables --db data.db

  # 2) 查看表结构
  python sqlite_io_tool.py schema --db data.db --table nodes

  # 3) 导出：表 -> JSON / CSV（格式由输出扩展名自动推断）
  python sqlite_io_tool.py export --db data.db --table nodes --out nodes.json
  python sqlite_io_tool.py export --db data.db --table nodes --out nodes.csv --where "type='Paper'"

  # 4) 导入：JSON / CSV -> 表（replace 清空重建 / append 追加 / upsert 按主键更新）
  python sqlite_io_tool.py import --db data.db --table nodes_backup --in nodes.json --mode replace
  python sqlite_io_tool.py import --db new.db --table words --in words.csv --mode append \
         --columns '{"id":"INTEGER PRIMARY KEY","word_en":"TEXT","word_cn":"TEXT"}'

库函数用法：
  from sqlite_io_tool import SqliteIO
  io = SqliteIO("data.db")
  io.export_table("nodes", "nodes.json")                 # 导出
  io.import_table("nodes", "nodes.json", mode="upsert")  # 导入
  io.close()

作者按：本工具与具体业务解耦；库表字段完全由调用方指定。
"""

import argparse
import base64
import csv
import json
import os
import sqlite3
from datetime import date, datetime, time


# ===========================================================================
# 核心类
# ===========================================================================
class SqliteIO:
    """通用 SQLite 导入导出。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    # ------------------------------------------------------------------
    # 元信息
    # ------------------------------------------------------------------
    def close(self):
        self.conn.close()

    def list_tables(self) -> list:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [r["name"] for r in rows]

    def table_exists(self, table: str) -> bool:
        r = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return r is not None

    def get_columns(self, table: str) -> list:
        """返回 [(name, type, pk, notnull, default)]。"""
        rows = self.conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        return [(r["name"], r["type"], r["pk"], r["notnull"], r["dflt_value"])
                for r in rows]

    def get_primary_key(self, table: str) -> str:
        cols = self.get_columns(table)
        pks = [c[0] for c in cols if c[2]]
        return pks[0] if pks else None

    # ------------------------------------------------------------------
    # 导出
    # ------------------------------------------------------------------
    def export_table(self, table: str, output: str, fmt: str = None,
                     where: str = None) -> int:
        """把表导出到 JSON / CSV，返回导出行数。fmt 缺省由 output 扩展名推断。"""
        if not self.table_exists(table):
            raise ValueError(f"表不存在: {table}")
        fmt = (fmt or self._fmt_of(output)).lower()
        columns = [c[0] for c in self.get_columns(table)]

        sql = f'SELECT * FROM "{table}"'
        params = ()
        if where:
            sql += f" WHERE {where}"
        rows = [self._row_to_dict(r, columns)
                for r in self.conn.execute(sql, params).fetchall()]

        if fmt == "json":
            self._write_json(rows, output)
        elif fmt == "csv":
            self._write_csv(rows, columns, output)
        else:
            raise ValueError(f"不支持的导出格式: {fmt}（可选 json / csv）")
        return len(rows)

    # ------------------------------------------------------------------
    # 导入
    # ------------------------------------------------------------------
    def import_table(self, table: str, source: str, fmt: str = None,
                     columns=None, pk: str = None, mode: str = "replace",
                     create_if_missing: bool = True) -> int:
        """从 JSON / CSV 导入到表，返回导入行数。

        参数：
          table   目标表名
          source  数据文件（.json 列表 / .csv）
          columns 字段定义，二选一：
                  - dict:  {"列名": "类型声明"}，如 {"id": "INTEGER PRIMARY KEY"}
                  - list:  ["列名1", "列名2"]（全部按 TEXT）
                  缺省时：表已存在则用现有列；否则从数据推断（JSON keys / CSV 表头）
          pk      主键列名（用于 upsert；表已存在时会自动探测，可省略）
          mode    replace（清空后写入）/ append（追加）/ upsert（按主键更新）
        """
        fmt = (fmt or self._fmt_of(source)).lower()
        records = self._read_json(source) if fmt == "json" else self._read_csv(source)

        if not records:
            return 0

        # 确定字段定义
        if columns is None:
            if self.table_exists(table):
                columns = [c[0] for c in self.get_columns(table)]
            else:
                columns = self._infer_columns(records)

        col_defs = self._normalize_columns(columns)   # {列名: 类型声明}

        # 建表
        if not self.table_exists(table):
            if not create_if_missing:
                raise ValueError(f"表 {table} 不存在且未允许自动建表")
            self._create_table(table, col_defs, pk)

        # 主键
        if pk is None and self.table_exists(table):
            pk = self.get_primary_key(table)
        if mode == "upsert" and not pk:
            raise ValueError("upsert 模式需要主键（pk 参数或表已含主键）")

        # 目标列（仅取表里存在的列）
        target_cols = [c[0] for c in self.get_columns(table)]
        keys = [k for k in col_defs if k in target_cols]

        # 写数据
        with self.conn:
            if mode == "replace":
                self.conn.execute(f'DELETE FROM "{table}"')
            for rec in records:
                if mode == "upsert":
                    self._upsert(table, keys, pk, rec)
                else:
                    self._insert(table, keys, rec)
        self.conn.commit()
        return len(records)

    # ------------------------------------------------------------------
    # 内部：建表 / 写入
    # ------------------------------------------------------------------
    def _create_table(self, table, col_defs, pk):
        parts = []
        for name, decl in col_defs.items():
            decl = decl or "TEXT"
            if pk and name == pk and "PRIMARY KEY" not in decl.upper():
                decl += " PRIMARY KEY"
            parts.append(f'"{name}" {decl}')
        ddl = f'CREATE TABLE "{table}" ({", ".join(parts)})'
        self.conn.execute(ddl)

    def _insert(self, table, keys, rec):
        cols = ", ".join(f'"{k}"' for k in keys)
        ph = ", ".join("?" for _ in keys)
        self.conn.execute(
            f'INSERT INTO "{table}" ({cols}) VALUES ({ph})',
            [self._serialize(rec.get(k)) for k in keys],
        )

    def _upsert(self, table, keys, pk, rec):
        cols = ", ".join(f'"{k}"' for k in keys)
        ph = ", ".join("?" for _ in keys)
        upd = ", ".join(f'"{k}"=excluded."{k}"' for k in keys if k != pk)
        self.conn.execute(
            f'INSERT INTO "{table}" ({cols}) VALUES ({ph}) '
            f'ON CONFLICT("{pk}") DO UPDATE SET {upd}',
            [self._serialize(rec.get(k)) for k in keys],
        )

    # ------------------------------------------------------------------
    # 内部：数据读取 / 写入
    # ------------------------------------------------------------------
    def _read_json(self, path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):           # 兼容 {"rows": [...]} 或单对象
            data = data.get("rows", data.get("data", [data]))
        if isinstance(data, dict):
            data = [data]
        return data

    def _read_csv(self, path):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def _write_json(self, rows, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2, default=str)

    def _write_csv(self, rows, columns, path):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=columns)
            w.writeheader()
            for r in rows:
                w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in columns})

    # ------------------------------------------------------------------
    # 内部：列 / 类型 / 序列化
    # ------------------------------------------------------------------
    def _normalize_columns(self, columns) -> dict:
        """把 columns 参数统一成 {列名: 类型声明}。"""
        if isinstance(columns, dict):
            return {k: (v or "TEXT") for k, v in columns.items()}
        if isinstance(columns, (list, tuple)):
            if columns and isinstance(columns[0], (list, tuple)):   # [(name, decl), ...]
                return {c[0]: c[1] for c in columns}
            return {c: "TEXT" for c in columns}                     # [name, ...]
        raise ValueError("columns 需为 dict（列名→类型）或 list（列名列表）")

    def _infer_columns(self, records) -> dict:
        """从记录推断列（JSON keys 或 CSV 表头），全部 TEXT。"""
        keys = []
        for rec in records:
            for k in rec.keys():
                if k not in keys:
                    keys.append(k)
        return {k: "TEXT" for k in keys}

    @staticmethod
    def _fmt_of(path: str) -> str:
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        if ext not in ("json", "csv"):
            raise ValueError(f"无法从扩展名推断格式: {path}（请用 --format 指定 json/csv）")
        return ext

    @staticmethod
    def _serialize(val):
        if isinstance(val, (bytes, bytearray)):
            return base64.b64encode(bytes(val)).decode("ascii")
        if isinstance(val, (datetime, date, time)):
            return val.isoformat()
        return val

    @staticmethod
    def _row_to_dict(row, columns):
        return {c: SqliteIO._serialize(row[c]) for c in columns}


# ===========================================================================
# CLI
# ===========================================================================
def main():
    ap = argparse.ArgumentParser(description="通用 SQLite 数据导入导出工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("tables",):
        p = sub.add_parser(name, help="列出所有表")
        p.add_argument("--db", required=True, help="数据库路径")

    p = sub.add_parser("schema", help="查看表结构")
    p.add_argument("--db", required=True)
    p.add_argument("--table", required=True)

    p = sub.add_parser("export", help="导出表到 JSON/CSV")
    p.add_argument("--db", required=True)
    p.add_argument("--table", required=True)
    p.add_argument("--out", required=True, help="输出文件(.json/.csv)")
    p.add_argument("--format", default=None, help="json/csv（缺省由 --out 扩展名推断）")
    p.add_argument("--where", default=None, help="WHERE 过滤条件")

    p = sub.add_parser("import", help="从 JSON/CSV 导入到表")
    p.add_argument("--db", required=True)
    p.add_argument("--table", required=True)
    p.add_argument("--in", dest="src", required=True, help="输入文件(.json/.csv)")
    p.add_argument("--format", default=None)
    p.add_argument("--columns", default=None, help="字段定义：JSON 字符串，如 '{\"id\":\"INTEGER PRIMARY KEY\"}' 或 '[\"a\",\"b\"]'")
    p.add_argument("--pk", default=None, help="主键列（upsert 用）")
    p.add_argument("--mode", default="replace", choices=["replace", "append", "upsert"])
    p.add_argument("--no-create", action="store_true", help="表不存在时不自动建表")

    args = ap.parse_args()
    io = SqliteIO(args.db)

    if args.cmd == "tables":
        for t in io.list_tables():
            print(t)

    elif args.cmd == "schema":
        cols = io.get_columns(args.table)
        if not cols:
            print(f"表不存在: {args.table}")
        for name, typ, pk, nn, dflt in cols:
            print(f"  {name:<24} {typ:<16} pk={pk} notnull={nn} default={dflt}")

    elif args.cmd == "export":
        n = io.export_table(args.table, args.out, args.format, args.where)
        print(f"已导出 {n} 行 -> {args.out}")

    elif args.cmd == "import":
        columns = json.loads(args.columns) if args.columns else None
        n = io.import_table(args.table, args.src, args.format, columns, args.pk,
                            args.mode, create_if_missing=not args.no_create)
        print(f"已导入 {n} 行 -> 表 {args.table}")

    io.close()


if __name__ == "__main__":
    main()
