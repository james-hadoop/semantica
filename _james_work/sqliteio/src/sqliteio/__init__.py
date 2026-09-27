"""Public API for :mod:`sqliteio`."""

from .core import SqliteIO
from .errors import (
    EmptyDataError,
    SqliteIOError,
    TableNotFoundError,
    UnsupportedFormatError,
    ValidationError,
)
from .models import ApiResponse, ColumnInfo, Repository

__version__ = "1.0.0"

__all__ = [
    "ApiResponse",
    "ColumnInfo",
    "EmptyDataError",
    "Repository",
    "SqliteIO",
    "SqliteIOError",
    "TableNotFoundError",
    "UnsupportedFormatError",
    "ValidationError",
    "__version__",
]
