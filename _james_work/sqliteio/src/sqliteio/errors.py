"""Typed exceptions for :mod:`sqliteio`.

Every public failure surfaces as one of these so callers can catch
specific conditions without string-matching.
"""

from __future__ import annotations


class SqliteIOError(Exception):
    """Base exception for all sqliteio errors."""


class TableNotFoundError(SqliteIOError):
    """Raised when a requested table does not exist."""

    def __init__(self, table: str) -> None:
        super().__init__(f"table does not exist: {table!r}")
        self.table = table


class ValidationError(SqliteIOError):
    """Raised when caller-supplied arguments are invalid."""


class UnsupportedFormatError(ValidationError):
    """Raised when an import/export format is not recognized."""

    def __init__(self, fmt: str) -> None:
        super().__init__(f"unsupported format: {fmt!r} (expected 'json' or 'csv')")
        self.fmt = fmt


class EmptyDataError(SqliteIOError):
    """Raised when an import source contains no records."""
