"""Data models: column metadata, API response envelope, repository protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable


@dataclass(frozen=True)
class ColumnInfo:
    """Metadata for a single table column (mirrors ``PRAGMA table_info``)."""

    name: str
    type: str = "TEXT"
    pk: bool = False
    notnull: bool = False
    default: Any = None


@dataclass(frozen=True)
class ApiResponse:
    """Uniform response envelope used by service-level integrations.

    ``success`` is the status flag; exactly one of ``data`` / ``error`` is set.
    ``meta`` carries pagination or summary metadata.
    """

    success: bool
    data: Any = None
    error: str | None = None
    meta: dict[str, Any] | None = None

    @classmethod
    def ok(cls, data: Any = None, meta: dict[str, Any] | None = None) -> "ApiResponse":
        return cls(success=True, data=data, error=None, meta=meta)

    @classmethod
    def fail(cls, error: str, meta: dict[str, Any] | None = None) -> "ApiResponse":
        return cls(success=False, data=None, error=error, meta=meta)


T = TypeVar("T")


@runtime_checkable
class Repository(Protocol[T]):
    """Minimal storage abstraction — business logic depends on this, not SQLite.

    Implementations may back onto SQLite, CSV, an API, or in-memory storage.
    """

    def find_all(self) -> list[T]: ...

    def find_by_id(self, id: str) -> T | None: ...

    def save(self, entity: T) -> T: ...

    def delete(self, id: str) -> None: ...
