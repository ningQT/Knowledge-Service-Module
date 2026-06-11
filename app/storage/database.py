"""Database backend abstract interface."""

from abc import ABC, abstractmethod
from typing import Any


class DatabaseBackend(ABC):
    """Abstract database backend for KSM storage.

    Phase 1: SQLiteBackend (SQLite + FTS5)
    Phase 2: MySQLBackend (MySQL + FULLTEXT)
    """

    @abstractmethod
    def execute(self, sql: str, params: tuple | list | None = None) -> list[dict[str, Any]]:
        """Execute a SQL query and return results as list of dicts."""
        ...

    @abstractmethod
    def executemany(self, sql: str, params_list: list[tuple | list]) -> None:
        """Execute a SQL statement for each set of parameters."""
        ...

    @abstractmethod
    def init_schema(self) -> None:
        """Initialize database schema (tables, indexes, FTS)."""
        ...

    @abstractmethod
    def fts_search(
        self,
        query: str,
        instance_ids: list[str],
        layer: int | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Full-text search using FTS5."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Close database connection."""
        ...

    # --- Settings table operations (Phase 3) ---

    def get_settings(self, key_prefix: str | None = None) -> list[dict[str, Any]]:
        """Read settings rows, optionally filtered by key prefix."""
        if key_prefix:
            return self.execute(
                "SELECT key, value, updated_at FROM settings WHERE key LIKE ? ORDER BY key",
                (f"{key_prefix}%",),
            )
        return self.execute("SELECT key, value, updated_at FROM settings ORDER BY key")

    def set_setting(self, key: str, value: str) -> None:
        """Upsert a single setting (value must be JSON-serialized by caller)."""
        self.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value),
        )

    def delete_settings(self, key_prefix: str) -> int:
        """Delete all settings matching a key prefix. Returns remaining row count (normally 0).

        设计文档 §3.2: 返回值设计为"剩余行数"而非"删除行数"。
        """
        self.execute("DELETE FROM settings WHERE key LIKE ?", (f"{key_prefix}%",))
        rows = self.execute(
            "SELECT COUNT(*) AS cnt FROM settings WHERE key LIKE ?", (f"{key_prefix}%",)
        )
        return rows[0]["cnt"] if rows else 0
