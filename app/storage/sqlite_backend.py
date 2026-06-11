"""SQLite database backend implementation."""

import json
import logging
import sqlite3
import shutil
import threading
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator
from typing import Any

from app.storage.database import DatabaseBackend

logger = logging.getLogger(__name__)


class SQLiteBackend(DatabaseBackend):
    """SQLite + FTS5 implementation of DatabaseBackend."""

    def __init__(
        self,
        db_path: str,
        *,
        backup_dir: str | None = None,
        backup_before_migration: bool = True,
    ):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._transaction_depth = 0
        self.backup_dir = backup_dir
        self.backup_before_migration = backup_before_migration
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def execute(self, sql: str, params: tuple | list | None = None) -> list[dict[str, Any]]:
        with self._lock:
            cursor = self.conn.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

            if cursor.description:
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
            if self._transaction_depth == 0:
                self.conn.commit()
            return []

    def executemany(self, sql: str, params_list: list[tuple | list]) -> None:
        with self._lock:
            cursor = self.conn.cursor()
            cursor.executemany(sql, params_list)
            if self._transaction_depth == 0:
                self.conn.commit()

    def init_schema(self) -> None:
        backup_path = self._backup_existing_database()
        schema_path = Path(__file__).parent / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")

        self.conn.executescript(schema_sql)
        self.conn.commit()
        self._record_schema_migration("0001_base_schema", "Base schema tables and indexes")
        self._ensure_notes_search_text_column()
        self._backfill_instance_ontology_enabled()
        fts_recreated = self._migrate_fts_if_needed()
        if fts_recreated:
            self.conn.executescript(schema_sql)
            self.conn.commit()
            self.rebuild_fts()
        if backup_path:
            self._record_schema_migration(
                "0002_startup_backup",
                f"Startup backup created at {backup_path}",
            )

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            outermost = self._transaction_depth == 0
            if outermost:
                self.conn.execute("BEGIN")
            self._transaction_depth += 1
            try:
                yield
            except Exception:
                self._transaction_depth -= 1
                if outermost:
                    self.conn.rollback()
                raise
            else:
                self._transaction_depth -= 1
                if outermost:
                    self.conn.commit()

    def _backup_existing_database(self) -> str | None:
        if not self.backup_before_migration or self.db_path == ":memory:":
            return None
        source = Path(self.db_path)
        if not source.exists() or source.stat().st_size == 0:
            return None
        backup_root = Path(self.backup_dir) if self.backup_dir else source.parent / "backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        target = backup_root / f"{source.stem}-{stamp}.db"
        shutil.copy2(source, target)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{source}{suffix}")
            if sidecar.exists():
                shutil.copy2(sidecar, backup_root / f"{source.stem}-{stamp}.db{suffix}")
        return str(target)

    def _record_schema_migration(self, version: str, description: str) -> None:
        self.execute(
            """INSERT OR IGNORE INTO schema_migrations (version, description, applied_at)
               VALUES (?, ?, datetime('now'))""",
            (version, description),
        )

    def _ensure_notes_search_text_column(self) -> None:
        """Add notes.search_text for existing databases."""
        try:
            rows = self.conn.execute("PRAGMA table_info(notes)").fetchall()
            if not rows:
                return
            columns = {row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in rows}
            if "search_text" not in columns:
                logger.info("Migrating notes: adding search_text column")
                self.conn.execute("ALTER TABLE notes ADD COLUMN search_text TEXT DEFAULT ''")
                self.conn.commit()
        except Exception as e:
            logger.warning("notes search_text migration failed: %s", e)

    def _backfill_instance_ontology_enabled(self) -> None:
        """Make legacy instance ontology state explicit without overriding user choices."""
        try:
            rows = self.conn.execute("SELECT id, config_json FROM instances").fetchall()
            if not rows:
                return
            changed = 0
            for row in rows:
                instance_id = row["id"] if isinstance(row, sqlite3.Row) else row[0]
                config_raw = row["config_json"] if isinstance(row, sqlite3.Row) else row[1]
                try:
                    config = json.loads(config_raw or "{}") if isinstance(config_raw, str) else (config_raw or {})
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Skipping ontology_enabled backfill for instance %s: invalid config_json", instance_id)
                    continue
                if not isinstance(config, dict) or "ontology_enabled" in config:
                    continue
                config["ontology_enabled"] = True
                self.conn.execute(
                    "UPDATE instances SET config_json = ? WHERE id = ?",
                    (json.dumps(config, ensure_ascii=False), instance_id),
                )
                changed += 1
            if changed:
                self.conn.commit()
                self._record_schema_migration(
                    "0003_backfill_instance_ontology_enabled",
                    f"Backfilled ontology_enabled=true for {changed} legacy instances",
                )
        except Exception as e:
            logger.warning("instance ontology_enabled backfill failed: %s", e)

    def _migrate_fts_if_needed(self) -> bool:
        """Drop notes_fts if its schema is not the canonical external-content form."""
        try:
            rows = self.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='notes_fts'"
            ).fetchall()
            if not rows:
                return False

            create_sql = rows[0][0] if isinstance(rows[0], tuple) else rows[0]["sql"]
            normalized = create_sql.lower()
            needs_recreate = (
                "content=notes" not in normalized
                or "content_rowid=id" not in normalized
                or "search_text" not in normalized
                or "tokenize='trigram'" not in normalized
            )
            if needs_recreate:
                logger.info("Migrating notes_fts to external-content trigram schema")
                self.conn.execute("DROP TABLE IF EXISTS notes_fts")
                self.conn.commit()
                return True
        except Exception as e:
            logger.warning("notes_fts migration check failed: %s", e)
        return False

    def migrate_fts_to_contentless(self) -> None:
        """Compatibility startup hook for old callers.

        The current schema uses an external content table. This method now makes
        sure the FTS index is populated and healthy after startup/migration.
        """
        try:
            health = self.check_fts_health()
            if not health["healthy"]:
                logger.info("Rebuilding unhealthy FTS index: %s", health)
                self.rebuild_fts()
        except Exception as e:
            logger.warning("FTS startup health check failed: %s", e)

    def check_fts_health(self) -> dict[str, Any]:
        """Return health counters for notes_fts against notes."""
        with self._lock:
            note_count = self._count_locked("SELECT COUNT(*) AS cnt FROM notes")
            docsize_count = self._count_locked("SELECT COUNT(*) AS cnt FROM notes_fts_docsize")
            missing_count = self._count_locked(
                """SELECT COUNT(*) AS cnt
                   FROM notes n
                   LEFT JOIN notes_fts_docsize d ON d.id = n.id
                   WHERE d.id IS NULL"""
            )
            orphan_count = self._count_locked(
                """SELECT COUNT(*) AS cnt
                   FROM notes_fts_docsize d
                   LEFT JOIN notes n ON n.id = d.id
                   WHERE n.id IS NULL"""
            )
        return {
            "notes_count": note_count,
            "docsize_count": docsize_count,
            "missing_rowids": missing_count,
            "orphan_rowids": orphan_count,
            "healthy": (
                note_count == docsize_count
                and missing_count == 0
                and orphan_count == 0
            ),
        }

    def rebuild_fts(self) -> dict[str, Any]:
        """Rebuild notes_fts from the external content table."""
        with self._lock:
            self._backfill_search_text_locked()
            self.conn.execute("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')")
            self.conn.commit()
        return self.check_fts_health()

    def _backfill_search_text_locked(self) -> None:
        rows = self.conn.execute(
            """SELECT id, title, frontmatter
               FROM notes
               WHERE search_text IS NULL OR trim(search_text) = ''"""
        ).fetchall()
        for row in rows:
            frontmatter = _load_json(row["frontmatter"])
            terms = [row["title"], *_frontmatter_search_terms(frontmatter)]
            search_text = " ".join(_dedupe_text(terms))
            self.conn.execute(
                "UPDATE notes SET search_text = ? WHERE id = ?",
                (search_text, row["id"]),
            )

    def _count_locked(self, sql: str) -> int:
        row = self.conn.execute(sql).fetchone()
        return int(row["cnt"] if row else 0)

    def fts_search(
        self,
        query: str,
        instance_ids: list[str],
        layer: int | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """FTS5 search using the external-content table with a subquery pattern.

        Reference: 详细设计文档 §9.3 R-07: FTS 必须用子查询，不能用 JOIN
        """
        placeholders = ",".join("?" * len(instance_ids))

        if layer is not None:
            sql = f"""
                SELECT n.instance_id, n.file_path, n.title, n.graph_layer, n.graph_role,
                       n.domain, n.kind, n.verification, n.frontmatter, n.type
                FROM notes n
                WHERE n.id IN (SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?)
                  AND n.instance_id IN ({placeholders})
                  AND n.graph_layer = ?
                ORDER BY n.id
                LIMIT ?
            """
            params = [query, *instance_ids, layer, limit]
        else:
            sql = f"""
                SELECT n.instance_id, n.file_path, n.title, n.graph_layer, n.graph_role,
                       n.domain, n.kind, n.verification, n.frontmatter, n.type
                FROM notes n
                WHERE n.id IN (SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?)
                  AND n.instance_id IN ({placeholders})
                ORDER BY n.id
                LIMIT ?
            """
            params = [query, *instance_ids, limit]

        rows = self.execute(sql, params)
        return rows

    def fts_search_experimental_rank(
        self,
        query: str,
        instance_ids: list[str],
        layer: int | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Experimental BM25/rank query for offline evaluation only."""
        placeholders = ",".join("?" * len(instance_ids))
        layer_sql = "AND n.graph_layer = ?" if layer is not None else ""
        sql = f"""
            SELECT n.instance_id, n.file_path, n.title, n.graph_layer, n.graph_role,
                   n.domain, n.kind, n.verification, n.frontmatter, n.type,
                   bm25(notes_fts) AS rank
            FROM notes_fts
            JOIN notes n ON n.id = notes_fts.rowid
            WHERE notes_fts MATCH ?
              AND n.instance_id IN ({placeholders})
              {layer_sql}
            ORDER BY rank
            LIMIT ?
        """
        params: list[Any] = [query, *instance_ids]
        if layer is not None:
            params.append(layer)
        params.append(limit)
        return self.execute(sql, params)

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None


def _load_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _frontmatter_search_terms(frontmatter: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in (
        "title",
        "domain",
        "kind",
        "aliases",
        "concepts",
        "core_concepts",
        "reading_path",
        "key_relations",
        "source_materials",
        "linked_maps",
    ):
        _append_search_values(frontmatter.get(field), values)
    return values


def _append_search_values(value: Any, values: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        text = value.strip()
        if text:
            values.append(text)
        return
    if isinstance(value, (int, float)):
        values.append(str(value))
        return
    if isinstance(value, list):
        for item in value:
            _append_search_values(item, values)
        return
    if isinstance(value, dict):
        for item in value.values():
            _append_search_values(item, values)


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
