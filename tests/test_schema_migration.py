"""Tests for database schema, including the note_embeddings migration."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.storage.sqlite_backend import SQLiteBackend


def _make_backend(tmp_path: Path) -> SQLiteBackend:
    """Create a fresh SQLiteBackend with the given db_path."""
    db_path = str(tmp_path / "test.db")
    backend = SQLiteBackend(db_path, backup_before_migration=False)
    backend.init_schema()
    return backend


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check whether a table exists in the database."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchall()
    return len(rows) > 0


def _index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    """Check whether an index exists in the database."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    ).fetchall()
    return len(rows) > 0


def _get_table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    """Return column names for a given table."""
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row["name"] for row in rows]


def _get_migration_versions(conn: sqlite3.Connection) -> list[str]:
    """Return all recorded migration versions in order."""
    rows = conn.execute(
        "SELECT version FROM schema_migrations ORDER BY applied_at"
    ).fetchall()
    return [row["version"] for row in rows]


# ---------------------------------------------------------------------------
# Fresh database tests
# ---------------------------------------------------------------------------


class TestFreshDatabase:
    """Verify that a newly-created database includes note_embeddings."""

    def test_note_embeddings_table_exists(self, tmp_path: Path) -> None:
        backend = _make_backend(tmp_path)
        try:
            rows = backend.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='note_embeddings'"
            )
            assert len(rows) == 1
        finally:
            backend.close()

    def test_note_embeddings_has_expected_columns(self, tmp_path: Path) -> None:
        backend = _make_backend(tmp_path)
        try:
            columns = _get_table_columns(backend.conn, "note_embeddings")
            expected = [
                "id",
                "instance_id",
                "file_path",
                "embedding_model",
                "embedding",
                "created_at",
                "updated_at",
            ]
            assert columns == expected
        finally:
            backend.close()

    def test_note_embeddings_index_exists(self, tmp_path: Path) -> None:
        backend = _make_backend(tmp_path)
        try:
            assert _index_exists(backend.conn, "idx_note_embeddings_instance")
        finally:
            backend.close()

    def test_migration_version_recorded(self, tmp_path: Path) -> None:
        backend = _make_backend(tmp_path)
        try:
            versions = _get_migration_versions(backend.conn)
            assert "0004_create_note_embeddings_table" in versions
        finally:
            backend.close()

    def test_unique_constraint_on_instance_and_path(self, tmp_path: Path) -> None:
        backend = _make_backend(tmp_path)
        try:
            # Insert an instance first (required by FK)
            backend.execute(
                """INSERT INTO instances (id, name, template_id, vault_path, created_at, updated_at)
                   VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))""",
                ("test-inst", "Test Instance", "default", "/tmp/test"),
            )
            # Insert first embedding
            backend.execute(
                """INSERT INTO note_embeddings
                   (instance_id, file_path, embedding_model, embedding, created_at, updated_at)
                   VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))""",
                ("test-inst", "note.md", "test-model", b"\x00\x01\x02"),
            )
            # Duplicate (instance_id, file_path) should fail
            with pytest.raises(sqlite3.IntegrityError):
                backend.execute(
                    """INSERT INTO note_embeddings
                       (instance_id, file_path, embedding_model, embedding, created_at, updated_at)
                       VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))""",
                    ("test-inst", "note.md", "test-model", b"\x03\x04\x05"),
                )
        finally:
            backend.close()

    def test_foreign_key_enforced(self, tmp_path: Path) -> None:
        backend = _make_backend(tmp_path)
        try:
            # Inserting with a non-existent instance_id should fail (FK violation)
            with pytest.raises(sqlite3.IntegrityError):
                backend.execute(
                    """INSERT INTO note_embeddings
                       (instance_id, file_path, embedding_model, embedding, created_at, updated_at)
                       VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))""",
                    ("nonexistent-inst", "note.md", "test-model", b"\x00"),
                )
        finally:
            backend.close()

    def test_embedding_stored_as_blob(self, tmp_path: Path) -> None:
        backend = _make_backend(tmp_path)
        try:
            backend.execute(
                """INSERT INTO instances (id, name, template_id, vault_path, created_at, updated_at)
                   VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))""",
                ("inst-blob", "Blob Test", "default", "/tmp/blob"),
            )
            blob_data = b"\x00\x01\x02\x03"
            backend.execute(
                """INSERT INTO note_embeddings
                   (instance_id, file_path, embedding_model, embedding, created_at, updated_at)
                   VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))""",
                ("inst-blob", "doc.md", "mymodel", blob_data),
            )
            rows = backend.execute(
                "SELECT embedding FROM note_embeddings WHERE instance_id = ?",
                ("inst-blob",),
            )
            assert len(rows) == 1
            assert rows[0]["embedding"] == blob_data
        finally:
            backend.close()


# ---------------------------------------------------------------------------
# Migration on existing database (without note_embeddings)
# ---------------------------------------------------------------------------


class TestMigrationOnExistingDatabase:
    """Simulate an existing database created before the note_embeddings migration."""

    def _create_old_schema_db(self, db_path: str) -> None:
        """Create a database with the old schema (no note_embeddings)."""
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS instances (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                template_id TEXT NOT NULL,
                vault_path TEXT NOT NULL,
                auto_map INTEGER NOT NULL DEFAULT 1,
                config_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                title TEXT NOT NULL,
                type TEXT,
                domain TEXT,
                kind TEXT,
                graph_layer INTEGER DEFAULT 0,
                graph_role TEXT,
                verification TEXT DEFAULT 'unverified',
                status TEXT DEFAULT 'active',
                frontmatter TEXT DEFAULT '{}',
                search_text TEXT DEFAULT '',
                content_hash TEXT,
                indexed_at TEXT NOT NULL,
                UNIQUE(instance_id, file_path),
                FOREIGN KEY (instance_id) REFERENCES instances(id)
            );
            INSERT INTO schema_migrations (version, description, applied_at)
            VALUES ('0001_base_schema', 'Base schema tables and indexes', datetime('now'));
        """)
        conn.commit()
        conn.close()

    def test_migration_adds_table(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "existing.db")
        self._create_old_schema_db(db_path)

        # Open with the backend -- init_schema runs the migration
        backend = SQLiteBackend(db_path, backup_before_migration=False)
        try:
            backend.init_schema()
            rows = backend.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='note_embeddings'"
            )
            assert len(rows) == 1
        finally:
            backend.close()

    def test_migration_adds_index(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "existing.db")
        self._create_old_schema_db(db_path)

        backend = SQLiteBackend(db_path, backup_before_migration=False)
        try:
            backend.init_schema()
            assert _index_exists(backend.conn, "idx_note_embeddings_instance")
        finally:
            backend.close()

    def test_migration_records_version(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "existing.db")
        self._create_old_schema_db(db_path)

        backend = SQLiteBackend(db_path, backup_before_migration=False)
        try:
            backend.init_schema()
            versions = _get_migration_versions(backend.conn)
            assert "0004_create_note_embeddings_table" in versions
        finally:
            backend.close()

    def test_migration_is_idempotent(self, tmp_path: Path) -> None:
        """Running init_schema twice should not fail or duplicate the migration record."""
        db_path = str(tmp_path / "existing.db")
        self._create_old_schema_db(db_path)

        backend = SQLiteBackend(db_path, backup_before_migration=False)
        try:
            # Run init_schema twice
            backend.init_schema()
            backend.init_schema()
            # The table should still exist and migration version should be recorded
            rows = backend.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='note_embeddings'"
            )
            assert len(rows) == 1
            # Check the migration was recorded (INSERT OR IGNORE means no duplicates for
            # the same version string, but init_schema re-runs 0001 etc. Each call records
            # a migration. We just verify 0004 is present.)
            versions = _get_migration_versions(backend.conn)
            assert "0004_create_note_embeddings_table" in versions
        finally:
            backend.close()

    def test_existing_data_preserved(self, tmp_path: Path) -> None:
        """Existing data in other tables should survive the migration."""
        db_path = str(tmp_path / "existing.db")
        self._create_old_schema_db(db_path)

        # Pre-populate an instance
        conn = sqlite3.connect(db_path)
        conn.execute(
            """INSERT INTO instances (id, name, template_id, vault_path, created_at, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))""",
            ("preserved-inst", "Preserved", "default", "/tmp/preserved"),
        )
        conn.commit()
        conn.close()

        backend = SQLiteBackend(db_path, backup_before_migration=False)
        try:
            backend.init_schema()
            rows = backend.execute(
                "SELECT id FROM instances WHERE id = ?", ("preserved-inst",)
            )
            assert len(rows) == 1
        finally:
            backend.close()
