"""SQLite database backend implementation."""

import json
import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
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
        # 后台写入与前台请求并发时，短暂锁冲突应等待而不是立即失败。
        self.conn.execute("PRAGMA busy_timeout=5000")

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
        self._ensure_account_access_schema()
        self._ensure_notes_search_text_column()
        self._backfill_instance_ontology_enabled()
        fts_recreated = self._migrate_fts_if_needed()
        if fts_recreated:
            self.conn.executescript(schema_sql)
            self.conn.commit()
            self.rebuild_fts()
        self._create_note_embeddings_table()
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
        # 使用微秒级时间戳，避免同一秒内重复备份相互覆盖。
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        target = backup_root / f"{source.stem}-{stamp}.db"
        # SQLite 在线备份在连接层生成一致性快照，不直接复制活动 WAL/SHM 文件。
        backup_conn = sqlite3.connect(target)
        try:
            self.conn.backup(backup_conn)
        finally:
            # sqlite3.Connection 的上下文管理器不会关闭连接，必须显式释放文件句柄。
            backup_conn.close()
        return str(target)

    def _record_schema_migration(self, version: str, description: str) -> None:
        self.execute(
            """INSERT OR IGNORE INTO schema_migrations (version, description, applied_at)
               VALUES (?, ?, datetime('now'))""",
            (version, description),
        )

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        """幂等为现有表补充列。

        Args:
            table: 目标表名，仅允许调用方传入固定内部表名。
            column: 目标列名。
            definition: SQLite ``ALTER TABLE`` 允许的列定义。

        Raises:
            sqlite3.Error: 当列探测或变更失败时向上抛出。
        """
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        if not rows:
            return
        columns = {
            row["name"] if isinstance(row, sqlite3.Row) else row[1]
            for row in rows
        }
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            self.conn.commit()

    def _ensure_account_access_schema(self) -> None:
        """为账户、实例所有权和 API Key 所有权补齐兼容结构。

        该方法在 ``schema.sql`` 执行后调用，负责旧库列补齐、旧数据回填和
        新索引创建。迁移保持幂等，不删除已有知识数据或凭证。
        """
        self._ensure_column(
            "admin_users",
            "role",
            "TEXT NOT NULL DEFAULT 'admin' CHECK(role IN ('admin', 'user'))",
        )
        self._ensure_column("admin_users", "enabled", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("instances", "owner_account_id", "TEXT")
        self._ensure_column("api_clients", "owner_account_id", "TEXT")

        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS account_instance_permissions (
                account_id TEXT NOT NULL,
                instance_id TEXT NOT NULL,
                permission TEXT NOT NULL CHECK(permission IN ('read', 'edit')),
                granted_by_account_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (account_id, instance_id),
                FOREIGN KEY (account_id) REFERENCES admin_users(id) ON DELETE CASCADE,
                FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE,
                FOREIGN KEY (granted_by_account_id) REFERENCES admin_users(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_instance_permissions_account
                ON account_instance_permissions(account_id);
            CREATE INDEX IF NOT EXISTS idx_instance_permissions_instance
                ON account_instance_permissions(instance_id, permission);
            CREATE INDEX IF NOT EXISTS idx_instances_owner
                ON instances(owner_account_id);
            CREATE INDEX IF NOT EXISTS idx_api_clients_owner
                ON api_clients(owner_account_id, enabled);
            """
        )

        admin_rows = self.conn.execute(
            "SELECT id FROM admin_users WHERE role = 'admin' ORDER BY created_at LIMIT 1"
        ).fetchall()
        if not admin_rows:
            legacy_rows = self.conn.execute(
                "SELECT id FROM admin_users ORDER BY created_at LIMIT 1"
            ).fetchall()
            if legacy_rows:
                admin_id = legacy_rows[0]["id"]
                self.conn.execute(
                    "UPDATE admin_users SET role = 'admin', enabled = 1 WHERE id = ?",
                    (admin_id,),
                )
                admin_rows = legacy_rows

        if admin_rows:
            admin_id = admin_rows[0]["id"]
            self.conn.execute(
                "UPDATE instances SET owner_account_id = ? WHERE owner_account_id IS NULL",
                (admin_id,),
            )
            self.conn.execute(
                "UPDATE api_clients SET owner_account_id = ? WHERE owner_account_id IS NULL",
                (admin_id,),
            )

        self.conn.commit()
        self._record_schema_migration(
            "0005_account_access_schema",
            "Added account roles, instance ownership, permissions and API key ownership",
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
                    config = (
                        json.loads(config_raw or "{}")
                        if isinstance(config_raw, str)
                        else (config_raw or {})
                    )
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "Skipping ontology_enabled backfill for instance %s: invalid config_json",
                        instance_id,
                    )
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

    def _create_note_embeddings_table(self) -> None:
        """Create note_embeddings table for existing databases."""
        try:
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS note_embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instance_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(instance_id, file_path),
                    FOREIGN KEY (instance_id) REFERENCES instances(id)
                )"""
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_note_embeddings_instance "
                "ON note_embeddings(instance_id)"
            )
            self.conn.commit()
            self._record_schema_migration(
                "0004_create_note_embeddings_table",
                "Created note_embeddings table for semantic deduplication",
            )
        except Exception as e:
            logger.warning("note_embeddings migration failed: %s", e)

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
        """FTS5 检索，按 bm25() 相关度降序返回（同分按入库序）。

        返回字段与改造前逐项一致（10 项），bm25 分数仅用于内部排序、不作为返回列。

        Reference: 详细设计文档 §9.3 R-07: FTS 匹配须封装在子查询/派生表内，
        不得直接把 notes_fts 作为 JOIN 左表回表

        实现要点：
        1. 用「派生表携带 bm25()」形态——要把 FTS 匹配关进派生表先算出
           「命中集 + 分数」，再按 rowid 回表。不能用 `n.id IN (SELECT rowid ...)`
           子查询：该形态下 bm25() 作用域不可及（实测报 no such column: notes_fts）。
        2. bm25() 返回负值，故 ASC 才是「相关度从高到低」；写成 DESC 会把最不相关的排在最前。
        3. LIMIT 在 ORDER BY 之后生效，被截断掉的是最不相关的条目，
           而非改造前那样丢掉入库较晚的条目。
        """
        placeholders = ",".join("?" * len(instance_ids))

        if layer is not None:
            sql = f"""
                SELECT n.instance_id, n.file_path, n.title, n.graph_layer, n.graph_role,
                       n.domain, n.kind, n.verification, n.frontmatter, n.type
                FROM notes n
                JOIN (SELECT rowid AS rid, bm25(notes_fts) AS rank
                        FROM notes_fts WHERE notes_fts MATCH ?) ft
                  ON ft.rid = n.id
                WHERE n.instance_id IN ({placeholders})
                  AND n.graph_layer = ?
                ORDER BY ft.rank ASC, n.id ASC
                LIMIT ?
            """
            params = [query, *instance_ids, layer, limit]
        else:
            sql = f"""
                SELECT n.instance_id, n.file_path, n.title, n.graph_layer, n.graph_role,
                       n.domain, n.kind, n.verification, n.frontmatter, n.type
                FROM notes n
                JOIN (SELECT rowid AS rid, bm25(notes_fts) AS rank
                        FROM notes_fts WHERE notes_fts MATCH ?) ft
                  ON ft.rid = n.id
                WHERE n.instance_id IN ({placeholders})
                ORDER BY ft.rank ASC, n.id ASC
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
        """FTS5 检索，按 bm25() 相关度降序返回（同分按 id 升序）。

        与 fts_search 共用同一派生表形态，但额外返回 bm25() 分数列。
        作为相关度排序的参考实现保留。

        Reference: 详细设计文档 §9.3 R-07: FTS 匹配须封装在子查询/派生表内，
        不得直接把 notes_fts 作为 JOIN 左表回表
        """
        placeholders = ",".join("?" * len(instance_ids))
        layer_sql = "AND n.graph_layer = ?" if layer is not None else ""
        # 派生表形态：先由 FTS 索引求出「命中 rowid + bm25 分数」，再按 rowid 回表。
        # 不可写成 FROM notes_fts JOIN notes（R-07）：那样会让 FTS 成为 JOIN 左表，
        # 查询计划退化为对 notes 的全表探测。
        sql = f"""
            SELECT n.instance_id, n.file_path, n.title, n.graph_layer, n.graph_role,
                   n.domain, n.kind, n.verification, n.frontmatter, n.type,
                   ft.rank
            FROM notes n
            JOIN (SELECT rowid AS rid, bm25(notes_fts) AS rank
                    FROM notes_fts WHERE notes_fts MATCH ?) ft
              ON ft.rid = n.id
            WHERE n.instance_id IN ({placeholders})
              {layer_sql}
            ORDER BY ft.rank ASC, n.id ASC
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
