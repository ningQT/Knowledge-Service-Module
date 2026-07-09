"""Tests for SemanticIndex – vector-based similarity search on note embeddings."""

from __future__ import annotations

import json
import math
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.llm.embedding import EmbeddingService
from app.storage.sqlite_backend import SQLiteBackend
from app.storage.semantic_index import SemanticIndex


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

_FIELD_TO_ALIAS: dict[str, str] = {
    "embedding_provider": "KSM_EMBEDDING_PROVIDER",
    "embedding_base_url": "KSM_EMBEDDING_BASE_URL",
    "embedding_api_key": "KSM_EMBEDDING_API_KEY",
    "embedding_model": "KSM_EMBEDDING_MODEL",
    "embedding_dimension": "KSM_EMBEDDING_DIMENSION",
    "embedding_batch_size": "KSM_EMBEDDING_BATCH_SIZE",
    "llm_base_url": "KSM_LLM_BASE_URL",
    "llm_api_key": "KSM_LLM_API_KEY",
}


def _make_settings(**overrides: Any) -> Settings:
    """Build a Settings instance with sensible defaults for tests."""
    import os

    defaults: dict[str, str] = {
        "KSM_EMBEDDING_PROVIDER": "openai",
        "KSM_EMBEDDING_BASE_URL": "https://api.example.com/v1",
        "KSM_EMBEDDING_API_KEY": "sk-test-key",
        "KSM_EMBEDDING_MODEL": "test-model",
        "KSM_EMBEDDING_DIMENSION": "4",
        "KSM_EMBEDDING_BATCH_SIZE": "32",
    }
    for k, v in overrides.items():
        alias = _FIELD_TO_ALIAS.get(k, k)
        defaults[alias] = str(v)
    with patch.dict(os.environ, defaults, clear=False):
        return Settings()


def _setup_instance(backend: SQLiteBackend, instance_id: str = "test-inst") -> None:
    """Insert a test instance row required by the FK constraint."""
    backend.execute(
        """INSERT OR IGNORE INTO instances (id, name, template_id, vault_path, created_at, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))""",
        (instance_id, "Test Instance", "default", "/tmp/test"),
    )


def _setup_note(
    backend: SQLiteBackend,
    instance_id: str,
    file_path: str,
    title: str = "Test Note",
    note_type: str | None = None,
) -> None:
    """Insert a note row (needed for find_similar enrichment)."""
    backend.execute(
        """INSERT OR IGNORE INTO notes
           (instance_id, file_path, title, type, indexed_at)
           VALUES (?, ?, ?, ?, datetime('now'))""",
        (instance_id, file_path, title, note_type),
    )


def _mock_embedding_service(vectors: dict[str, list[float]] | None = None) -> EmbeddingService:
    """Create an EmbeddingService with mocked API calls.

    ``vectors`` maps text → vector.  If a text is not in the dict, returns
    a deterministic 4-dim vector based on the text's hash.
    """
    settings = _make_settings()
    svc = EmbeddingService(settings)

    _vectors = vectors or {}

    def _fake_embed(text: str) -> list[float]:
        if text in _vectors:
            return _vectors[text]
        # Deterministic fallback: simple hash-based vector
        h = hash(text) % 1000
        return [float(h), float(h + 1), float(h + 2), float(h + 3)]

    svc.embed_text = _fake_embed  # type: ignore[method-assign]
    return svc


def _make_index(
    tmp_path: Any,
    *,
    embedding_service: EmbeddingService | None = None,
) -> tuple[SemanticIndex, SQLiteBackend]:
    """Create a SemanticIndex backed by a fresh in-memory SQLite database."""
    db = SQLiteBackend(":memory:", backup_before_migration=False)
    db.init_schema()
    svc = embedding_service or _mock_embedding_service()
    return SemanticIndex(db, svc), db


# ---------------------------------------------------------------------------
# _build_embed_text tests
# ---------------------------------------------------------------------------


class TestBuildEmbedText:
    """Verify the text format sent to the embedding API."""

    def test_basic(self) -> None:
        result = SemanticIndex._build_embed_text("Title", "Summary text", ["concept1", "concept2"])
        assert result == "Title\nSummary text\nconcept1, concept2"

    def test_empty_concepts(self) -> None:
        result = SemanticIndex._build_embed_text("T", "S", [])
        assert result == "T\nS\n"

    def test_empty_summary(self) -> None:
        result = SemanticIndex._build_embed_text("T", "", ["c"])
        assert result == "T\n\nc"

    def test_multiline_summary(self) -> None:
        result = SemanticIndex._build_embed_text("T", "line1\nline2", [])
        assert result == "T\nline1\nline2\n"


# ---------------------------------------------------------------------------
# _vector_to_blob / _blob_to_vector tests
# ---------------------------------------------------------------------------


class TestVectorBlobConversion:
    """Round-trip serialization of float vectors."""

    def test_roundtrip(self) -> None:
        vec = [1.0, 2.5, -3.14, 0.0]
        blob = SemanticIndex._vector_to_blob(vec)
        assert isinstance(blob, bytes)
        restored = SemanticIndex._blob_to_vector(blob)
        assert len(restored) == len(vec)
        for a, b in zip(vec, restored, strict=True):
            assert math.isclose(a, b)

    def test_empty_vector(self) -> None:
        blob = SemanticIndex._vector_to_blob([])
        assert json.loads(blob) == []
        assert SemanticIndex._blob_to_vector(blob) == []

    def test_corrupt_blob(self) -> None:
        assert SemanticIndex._blob_to_vector(b"not-json") == []

    def test_string_input(self) -> None:
        """_blob_to_vector should accept a plain string as well."""
        blob_str = json.dumps([1.0, 2.0])
        assert SemanticIndex._blob_to_vector(blob_str) == [1.0, 2.0]


# ---------------------------------------------------------------------------
# add_note tests
# ---------------------------------------------------------------------------


class TestAddNote:
    """Storing note embeddings."""

    def test_success(self, tmp_path: Any) -> None:
        idx, db = _make_index(tmp_path)
        _setup_instance(db)
        result = idx.add_note("test-inst", "note.md", "Title", "Summary", ["c1"])
        assert result is True
        # Verify stored in DB
        rows = db.execute(
            "SELECT * FROM note_embeddings WHERE instance_id = 'test-inst'"
        )
        assert len(rows) == 1
        assert rows[0]["file_path"] == "note.md"
        assert rows[0]["embedding_model"] == "test-model"

    def test_embedding_failure_returns_false(self, tmp_path: Any) -> None:
        """When the embedding service returns [], add_note should return False."""
        svc = _mock_embedding_service()
        svc.embed_text = lambda text: []  # type: ignore[method-assign]
        idx, db = _make_index(tmp_path, embedding_service=svc)
        _setup_instance(db)
        result = idx.add_note("test-inst", "note.md", "T", "S", [])
        assert result is False
        rows = db.execute(
            "SELECT COUNT(*) AS cnt FROM note_embeddings WHERE instance_id = 'test-inst'"
        )
        assert rows[0]["cnt"] == 0

    def test_upsert_replaces_existing(self, tmp_path: Any) -> None:
        """Adding the same (instance_id, file_path) twice should update, not duplicate."""
        idx, db = _make_index(tmp_path)
        _setup_instance(db)
        idx.add_note("test-inst", "a.md", "V1", "S", [])
        idx.add_note("test-inst", "a.md", "V2", "S", [])
        rows = db.execute(
            "SELECT COUNT(*) AS cnt FROM note_embeddings WHERE instance_id = 'test-inst'"
        )
        assert rows[0]["cnt"] == 1

    def test_multiple_notes(self, tmp_path: Any) -> None:
        idx, db = _make_index(tmp_path)
        _setup_instance(db)
        idx.add_note("test-inst", "a.md", "A", "Sa", [])
        idx.add_note("test-inst", "b.md", "B", "Sb", [])
        rows = db.execute(
            "SELECT COUNT(*) AS cnt FROM note_embeddings WHERE instance_id = 'test-inst'"
        )
        assert rows[0]["cnt"] == 2


# ---------------------------------------------------------------------------
# find_similar tests
# ---------------------------------------------------------------------------


class TestFindSimilar:
    """Cosine-similarity search."""

    def _build_index_with_vectors(
        self, tmp_path: Any
    ) -> tuple[SemanticIndex, SQLiteBackend]:
        """Create an index with 3 notes whose vectors are close or far apart."""
        # Vector definitions: v_similar and v_close are near-identical;
        # v_far is orthogonal.
        v_similar = [1.0, 0.0, 0.0, 0.0]
        v_close = [0.98, 0.2, 0.0, 0.0]
        v_far = [0.0, 0.0, 1.0, 0.0]

        svc = _mock_embedding_service({
            "query-a\nquery summary\n": v_similar,
            "Title-A\nSummary-A\nconcept1": v_similar,
            "Title-B\nSummary-B\nconcept2": v_close,
            "Title-C\nSummary-C\nconcept3": v_far,
        })

        idx, db = _make_index(tmp_path, embedding_service=svc)
        _setup_instance(db)
        _setup_note(db, "test-inst", "a.md", "Note A", "source")
        _setup_note(db, "test-inst", "b.md", "Note B", "card")
        _setup_note(db, "test-inst", "c.md", "Note C", "map")

        # Embed and store notes
        # add_note calls embed_text internally, which is mocked per text
        idx.add_note("test-inst", "a.md", "Title-A", "Summary-A", ["concept1"])
        idx.add_note("test-inst", "b.md", "Title-B", "Summary-B", ["concept2"])
        idx.add_note("test-inst", "c.md", "Title-C", "Summary-C", ["concept3"])
        return idx, db

    def test_returns_similar_notes_above_threshold(self, tmp_path: Any) -> None:
        idx, _ = self._build_index_with_vectors(tmp_path)
        results = idx.find_similar(
            "test-inst", "query-a\nquery summary\n", threshold=0.5, top_k=10
        )
        file_paths = [r["file_path"] for r in results]
        # a.md and b.md should be similar; c.md should be excluded
        assert "a.md" in file_paths
        assert "b.md" in file_paths
        assert "c.md" not in file_paths

    def test_top_k_limits_results(self, tmp_path: Any) -> None:
        idx, _ = self._build_index_with_vectors(tmp_path)
        results = idx.find_similar(
            "test-inst", "query-a\nquery summary\n", threshold=0.0, top_k=1
        )
        assert len(results) == 1

    def test_results_sorted_by_score_desc(self, tmp_path: Any) -> None:
        idx, _ = self._build_index_with_vectors(tmp_path)
        results = idx.find_similar(
            "test-inst", "query-a\nquery summary\n", threshold=0.0, top_k=10
        )
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_results_enriched_with_title_and_type(self, tmp_path: Any) -> None:
        idx, _ = self._build_index_with_vectors(tmp_path)
        results = idx.find_similar(
            "test-inst", "query-a\nquery summary\n", threshold=0.0, top_k=10
        )
        by_path = {r["file_path"]: r for r in results}
        assert by_path["a.md"]["title"] == "Note A"
        assert by_path["a.md"]["type"] == "source"
        assert by_path["b.md"]["title"] == "Note B"
        assert by_path["b.md"]["type"] == "card"

    def test_empty_instance_returns_empty(self, tmp_path: Any) -> None:
        idx, db = _make_index(tmp_path)
        _setup_instance(db)
        results = idx.find_similar(
            "test-inst", "query", threshold=0.0, top_k=10
        )
        assert results == []

    def test_high_threshold_filters_all(self, tmp_path: Any) -> None:
        idx, _ = self._build_index_with_vectors(tmp_path)
        results = idx.find_similar(
            "test-inst", "query-a\nquery summary\n", threshold=0.999, top_k=10
        )
        # Only exact match (a.md with same vector) might pass, but with mocked
        # embeddings the query and note a.md get the same vector so score=1.0
        assert all(r["score"] >= 0.999 for r in results)

    def test_embedding_failure_returns_empty(self, tmp_path: Any) -> None:
        svc = _mock_embedding_service()
        svc.embed_text = lambda text: []  # type: ignore[method-assign]
        idx, db = _make_index(tmp_path, embedding_service=svc)
        _setup_instance(db)
        results = idx.find_similar("test-inst", "query", threshold=0.0)
        assert results == []


# ---------------------------------------------------------------------------
# remove_note tests
# ---------------------------------------------------------------------------


class TestRemoveNote:
    """Deleting note embeddings."""

    def test_removes_existing(self, tmp_path: Any) -> None:
        idx, db = _make_index(tmp_path)
        _setup_instance(db)
        idx.add_note("test-inst", "a.md", "T", "S", [])
        assert idx.remove_note("test-inst", "a.md") is True
        rows = db.execute(
            "SELECT COUNT(*) AS cnt FROM note_embeddings WHERE instance_id = 'test-inst'"
        )
        assert rows[0]["cnt"] == 0

    def test_removes_only_target(self, tmp_path: Any) -> None:
        idx, db = _make_index(tmp_path)
        _setup_instance(db)
        idx.add_note("test-inst", "a.md", "T", "S", [])
        idx.add_note("test-inst", "b.md", "T", "S", [])
        idx.remove_note("test-inst", "a.md")
        rows = db.execute(
            "SELECT file_path FROM note_embeddings WHERE instance_id = 'test-inst'"
        )
        assert len(rows) == 1
        assert rows[0]["file_path"] == "b.md"

    def test_nonexistent_returns_false(self, tmp_path: Any) -> None:
        idx, db = _make_index(tmp_path)
        _setup_instance(db)
        assert idx.remove_note("test-inst", "no-such.md") is False


# ---------------------------------------------------------------------------
# rebuild tests
# ---------------------------------------------------------------------------


class TestRebuild:
    """Rebuilding the in-memory index."""

    def test_returns_count(self, tmp_path: Any) -> None:
        idx, db = _make_index(tmp_path)
        _setup_instance(db)
        idx.add_note("test-inst", "a.md", "T", "S", [])
        idx.add_note("test-inst", "b.md", "T", "S", [])
        count = idx.rebuild("test-inst")
        assert count == 2

    def test_empty_instance_returns_zero(self, tmp_path: Any) -> None:
        idx, db = _make_index(tmp_path)
        _setup_instance(db)
        count = idx.rebuild("test-inst")
        assert count == 0

    def test_isolation_between_instances(self, tmp_path: Any) -> None:
        """Rebuild for one instance should not count another instance's embeddings."""
        idx, db = _make_index(tmp_path)
        _setup_instance(db, "inst-a")
        _setup_instance(db, "inst-b")
        idx.add_note("inst-a", "a.md", "T", "S", [])
        idx.add_note("inst-a", "b.md", "T", "S", [])
        idx.add_note("inst-b", "x.md", "T", "S", [])
        assert idx.rebuild("inst-a") == 2
        assert idx.rebuild("inst-b") == 1


# ---------------------------------------------------------------------------
# Integration: full add-find-remove cycle
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """Full lifecycle: add -> find_similar -> remove -> rebuild."""

    def test_full_cycle(self, tmp_path: Any) -> None:
        v1 = [1.0, 0.0, 0.0, 0.0]
        v2 = [0.0, 1.0, 0.0, 0.0]
        svc = _mock_embedding_service({
            "query": v1,
            "Alpha\nFirst note\n": v1,
            "Beta\nSecond note\n": v2,
        })
        idx, db = _make_index(tmp_path, embedding_service=svc)
        _setup_instance(db)
        _setup_note(db, "test-inst", "alpha.md", "Alpha", "source")
        _setup_note(db, "test-inst", "beta.md", "Beta", "card")

        # Add
        assert idx.add_note("test-inst", "alpha.md", "Alpha", "First note", []) is True
        assert idx.add_note("test-inst", "beta.md", "Beta", "Second note", []) is True

        # Find similar (query = v1, so alpha should match)
        results = idx.find_similar("test-inst", "query", threshold=0.5, top_k=10)
        assert len(results) >= 1
        assert results[0]["file_path"] == "alpha.md"
        assert results[0]["title"] == "Alpha"
        assert results[0]["type"] == "source"

        # Remove
        assert idx.remove_note("test-inst", "alpha.md") is True
        results_after = idx.find_similar("test-inst", "query", threshold=0.5, top_k=10)
        alpha_still = [r for r in results_after if r["file_path"] == "alpha.md"]
        assert len(alpha_still) == 0

        # Rebuild
        count = idx.rebuild("test-inst")
        assert count == 1  # only beta.md remains
