# sqliteio

Production-grade, **schema-agnostic** SQLite import/export toolkit — a typed Python library
plus a command-line interface. Specify the database path, table name, columns, and primary key,
and it works against **any** SQLite table in **any** scenario.

## Features

- **Export** any table to JSON or CSV (auto column detection, `WHERE` filtering, safe
  serialization of `BLOB` → base64 and `date`/`datetime` → ISO 8601)
- **Import** JSON or CSV into any table with three write modes:
  - `replace` — truncate then load
  - `append` — insert only
  - `upsert` — update by primary key (`INSERT ... ON CONFLICT`)
- **Auto-create tables** from a column definition when the target does not exist
- **SQL-injection-safe** identifier quoting (table/column names are always double-quoted
  and escaped — values are always parameterized)
- Typed exceptions, a `Repository` protocol, and a uniform API response envelope

## Install

```bash
pip install -e .            # from this directory
# or, once published:
# pip install sqliteio
```

## CLI

```bash
# list tables / inspect schema
sqliteio tables --db data.db
sqliteio schema --db data.db --table nodes

# export (format inferred from --out extension)
sqliteio export --db data.db --table nodes --out nodes.json
sqliteio export --db data.db --table nodes --out papers.csv --where "type='Paper'"

# import (columns given as a JSON map; auto-creates the table)
sqliteio import --db new.db --table nodes --in nodes.json --mode replace \
    --columns '{"id":"TEXT PRIMARY KEY","type":"TEXT","label":"TEXT"}'

# upsert by primary key
sqliteio import --db data.db --table nodes --in patch.json --mode upsert --pk id
```

## Python API

```python
from sqliteio import SqliteIO

with SqliteIO("data.db") as io:
    # introspect
    io.list_tables()                  # -> ["edges", "nodes"]
    io.get_columns("nodes")           # -> [ColumnInfo(name="id", type="TEXT", pk=True, ...)]

    # export
    io.export_table("nodes", "nodes.json")                # -> 107
    io.export_table("nodes", "papers.csv", where="type='Paper'")

    # import
    io.import_table("nodes", "nodes.json", mode="upsert", pk="id")
    io.import_table(
        "words",
        "words.csv",
        columns={"id": "INTEGER PRIMARY KEY", "word_en": "TEXT", "word_cn": "TEXT"},
        mode="append",
    )
```

## Data contracts

### API response envelope

Service-level callers (e.g. an HTTP layer) can wrap results uniformly:

```python
from sqliteio import ApiResponse

resp = ApiResponse.ok(data={"rows": 3}, meta={"total": 3})
resp = ApiResponse.fail(error="table 'x' not found")
```

### Repository protocol

```python
from sqliteio import Repository

def run(repo: Repository) -> None:   # business logic depends on the interface, not SQLite
    ...
```

## Layout

```
sqliteio/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/sqliteio/
│   ├── __init__.py     # public API + __version__
│   ├── core.py         # SqliteIO
│   ├── models.py       # ColumnInfo / ApiResponse
│   ├── errors.py       # typed exceptions
│   └── cli.py          # command line
└── tests/
    └── test_sqliteio.py
```

## Development

```bash
pip install -e '.[dev]'
pytest -q
black src tests
ruff src tests
```

## License

MIT
