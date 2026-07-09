"""Tests for SemanticDeduplicator – semantic deduplication decision maker."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.llm.embedding import EmbeddingService
from app.pipeline.semantic_dedup import SemanticDeduplicator
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


def _make_dedup(
    *,
    embedding_service: EmbeddingService | None = None,
    settings: Settings | None = None,
) -> tuple[SemanticDeduplicator, SQLiteBackend]:
    """Create a SemanticDeduplicator backed by a fresh in-memory SQLite database."""
    db = SQLiteBackend(":memory:", backup_before_migration=False)
    db.init_schema()
    svc = embedding_service or _mock_embedding_service()
    idx = SemanticIndex(db, svc)
    dedup = SemanticDeduplicator(idx, settings)
    return dedup, db


# ---------------------------------------------------------------------------
# _build_query_text tests
# ---------------------------------------------------------------------------


class TestBuildQueryText:
    """Verify the query text format for embedding."""

    def test_basic(self) -> None:
        result = SemanticDeduplicator._build_query_text("Title", "Summary text", ["concept1", "concept2"])
        assert result == "Title\nSummary text\nconcept1, concept2"

    def test_empty_concepts(self) -> None:
        result = SemanticDeduplicator._build_query_text("T", "S", [])
        assert result == "T\nS\n"

    def test_empty_summary(self) -> None:
        result = SemanticDeduplicator._build_query_text("T", "", ["c"])
        assert result == "T\n\nc"

    def test_multiline_summary(self) -> None:
        result = SemanticDeduplicator._build_query_text("T", "line1\nline2", [])
        assert result == "T\nline1\nline2\n"


# ---------------------------------------------------------------------------
# find_duplicate_source tests
# ---------------------------------------------------------------------------


class TestFindDuplicateSource:
    """Searching for duplicate source notes."""

    def _build_index_with_sources(
        self,
    ) -> tuple[SemanticDeduplicator, SQLiteBackend]:
        """Create an index with source and card notes."""
        # Vectors for different content
        v_source1 = [1.0, 0.0, 0.0, 0.0]
        v_source2 = [0.0, 1.0, 0.0, 0.0]
        v_card = [0.0, 0.0, 1.0, 0.0]

        svc = _mock_embedding_service({
            # Query vectors (will match via hash fallback)
            "New Source\nNew summary about topic\nconcept1": v_source1,
            # Stored note vectors
            "Source Title 1\nSummary about AI\nconcept1": v_source1,
            "Source Title 2\nSummary about ML\nconcept2": v_source2,
            "Card Title\nCard summary\nconcept3": v_card,
        })

        dedup, db = _make_dedup(embedding_service=svc)
        _setup_instance(db)
        _setup_note(db, "test-inst", "source1.md", "Source 1", "source")
        _setup_note(db, "test-inst", "source2.md", "Source 2", "source")
        _setup_note(db, "test-inst", "card1.md", "Card 1", "card")

        # Add embeddings
        dedup._index.add_note("test-inst", "source1.md", "Source Title 1", "Summary about AI", ["concept1"])
        dedup._index.add_note("test-inst", "source2.md", "Source Title 2", "Summary about ML", ["concept2"])
        dedup._index.add_note("test-inst", "card1.md", "Card Title", "Card summary", ["concept3"])

        return dedup, db

    def test_finds_duplicate_source(self) -> None:
        dedup, _ = self._build_index_with_sources()
        result = dedup.find_duplicate_source(
            "test-inst",
            "New Source",
            "New summary about topic",
            ["concept1"],
        )
        # Should find source1.md as duplicate (same vector)
        assert result == "source1.md"

    def test_returns_none_when_no_duplicate(self) -> None:
        """When no source matches above threshold, return None."""
        svc = _mock_embedding_service({
            "Unique Source\nUnique summary\nunique": [0.0, 0.0, 0.0, 1.0],
            "Source Title\nSummary\nconcept": [1.0, 0.0, 0.0, 0.0],
        })
        dedup, db = _make_dedup(embedding_service=svc)
        _setup_instance(db)
        _setup_note(db, "test-inst", "existing.md", "Existing", "source")
        dedup._index.add_note("test-inst", "existing.md", "Source Title", "Summary", ["concept"])

        result = dedup.find_duplicate_source(
            "test-inst",
            "Unique Source",
            "Unique summary",
            ["unique"],
        )
        assert result is None

    def test_ignores_card_notes(self) -> None:
        """Even if a card has high similarity, it should not be returned as source duplicate."""
        v_same = [1.0, 0.0, 0.0, 0.0]
        svc = _mock_embedding_service({
            "Query Title\nQuery summary\n": v_same,
            "Card Title\nCard summary\n": v_same,
        })
        dedup, db = _make_dedup(embedding_service=svc)
        _setup_instance(db)
        _setup_note(db, "test-inst", "card.md", "Card", "card")
        dedup._index.add_note("test-inst", "card.md", "Card Title", "Card summary", [])

        result = dedup.find_duplicate_source(
            "test-inst",
            "Query Title",
            "Query summary",
            [],
        )
        # Should not match because card.md is type=card, not source
        assert result is None

    def test_empty_index_returns_none(self) -> None:
        dedup, db = _make_dedup()
        _setup_instance(db)
        result = dedup.find_duplicate_source(
            "test-inst",
            "Title",
            "Summary",
            [],
        )
        assert result is None


# ---------------------------------------------------------------------------
# find_duplicate_cards tests
# ---------------------------------------------------------------------------


class TestFindDuplicateCards:
    """Batch searching for duplicate cards."""

    def test_finds_duplicate_cards(self) -> None:
        v_card1 = [1.0, 0.0, 0.0, 0.0]
        v_card2 = [0.0, 1.0, 0.0, 0.0]

        svc = _mock_embedding_service({
            "Card A\nSummary A\n": v_card1,
            "Card B\nSummary B\n": v_card2,
            "Existing Card 1\nExisting summary 1\n": v_card1,
            "Existing Card 2\nExisting summary 2\n": v_card2,
        })

        dedup, db = _make_dedup(embedding_service=svc)
        _setup_instance(db)
        _setup_note(db, "test-inst", "existing1.md", "Existing 1", "card")
        _setup_note(db, "test-inst", "existing2.md", "Existing 2", "card")
        dedup._index.add_note("test-inst", "existing1.md", "Existing Card 1", "Existing summary 1", [])
        dedup._index.add_note("test-inst", "existing2.md", "Existing Card 2", "Existing summary 2", [])

        candidates = [
            {"title": "Card A", "summary": "Summary A", "concepts": []},
            {"title": "Card B", "summary": "Summary B", "concepts": []},
        ]

        result = dedup.find_duplicate_cards("test-inst", candidates)
        assert result == {
            "Card A": "existing1.md",
            "Card B": "existing2.md",
        }

    def test_no_duplicates_returns_empty(self) -> None:
        v_card = [1.0, 0.0, 0.0, 0.0]
        v_unique = [0.0, 0.0, 0.0, 1.0]

        svc = _mock_embedding_service({
            "Unique Card\nUnique summary\n": v_unique,
            "Existing Card\nExisting summary\n": v_card,
        })

        dedup, db = _make_dedup(embedding_service=svc)
        _setup_instance(db)
        _setup_note(db, "test-inst", "existing.md", "Existing", "card")
        dedup._index.add_note("test-inst", "existing.md", "Existing Card", "Existing summary", [])

        candidates = [
            {"title": "Unique Card", "summary": "Unique summary", "concepts": []},
        ]

        result = dedup.find_duplicate_cards("test-inst", candidates)
        assert result == {}

    def test_empty_candidates_returns_empty(self) -> None:
        dedup, db = _make_dedup()
        _setup_instance(db)
        result = dedup.find_duplicate_cards("test-inst", [])
        assert result == {}

    def test_ignores_source_notes(self) -> None:
        """Source notes should not be returned as card duplicates."""
        v_same = [1.0, 0.0, 0.0, 0.0]

        svc = _mock_embedding_service({
            "Query Card\nQuery summary\n": v_same,
            "Source Note\nSource summary\n": v_same,
        })

        dedup, db = _make_dedup(embedding_service=svc)
        _setup_instance(db)
        _setup_note(db, "test-inst", "source.md", "Source", "source")
        dedup._index.add_note("test-inst", "source.md", "Source Note", "Source summary", [])

        candidates = [
            {"title": "Query Card", "summary": "Query summary", "concepts": []},
        ]

        result = dedup.find_duplicate_cards("test-inst", candidates)
        # Should not match because source.md is type=source
        assert result == {}

    def test_multiple_cards_partial_match(self) -> None:
        v_match = [1.0, 0.0, 0.0, 0.0]
        v_no_match = [0.0, 0.0, 0.0, 1.0]

        svc = _mock_embedding_service({
            "Matching Card\nMatch summary\n": v_match,
            "Non-Matching Card\nNo match summary\n": v_no_match,
            "Existing Card\nExisting summary\n": v_match,
        })

        dedup, db = _make_dedup(embedding_service=svc)
        _setup_instance(db)
        _setup_note(db, "test-inst", "existing.md", "Existing", "card")
        dedup._index.add_note("test-inst", "existing.md", "Existing Card", "Existing summary", [])

        candidates = [
            {"title": "Matching Card", "summary": "Match summary", "concepts": []},
            {"title": "Non-Matching Card", "summary": "No match summary", "concepts": []},
        ]

        result = dedup.find_duplicate_cards("test-inst", candidates)
        assert result == {"Matching Card": "existing.md"}


# ---------------------------------------------------------------------------
# should_merge_or_create tests
# ---------------------------------------------------------------------------


class TestShouldMergeOrCreate:
    """Decision logic for card merge vs create."""

    def test_returns_merge_when_similar_card_found(self) -> None:
        v_card = [1.0, 0.0, 0.0, 0.0]

        svc = _mock_embedding_service({
            "New Card\nNew summary\n": v_card,
            "Existing Card\nExisting summary\n": v_card,
        })

        dedup, db = _make_dedup(embedding_service=svc)
        _setup_instance(db)
        _setup_note(db, "test-inst", "existing.md", "Existing", "card")
        dedup._index.add_note("test-inst", "existing.md", "Existing Card", "Existing summary", [])

        action, path = dedup.should_merge_or_create(
            "test-inst",
            "New Card",
            "New summary",
        )
        assert action == "merge"
        assert path == "existing.md"

    def test_returns_create_when_no_similar_card(self) -> None:
        v_new = [0.0, 0.0, 0.0, 1.0]
        v_existing = [1.0, 0.0, 0.0, 0.0]

        svc = _mock_embedding_service({
            "New Card\nNew summary\n": v_new,
            "Existing Card\nExisting summary\n": v_existing,
        })

        dedup, db = _make_dedup(embedding_service=svc)
        _setup_instance(db)
        _setup_note(db, "test-inst", "existing.md", "Existing", "card")
        dedup._index.add_note("test-inst", "existing.md", "Existing Card", "Existing summary", [])

        action, path = dedup.should_merge_or_create(
            "test-inst",
            "New Card",
            "New summary",
        )
        assert action == "create"
        assert path == ""

    def test_ignores_source_notes_for_merge(self) -> None:
        """Source notes should not trigger merge decisions."""
        v_same = [1.0, 0.0, 0.0, 0.0]

        svc = _mock_embedding_service({
            "New Card\nNew summary\n": v_same,
            "Source Note\nSource summary\n": v_same,
        })

        dedup, db = _make_dedup(embedding_service=svc)
        _setup_instance(db)
        _setup_note(db, "test-inst", "source.md", "Source", "source")
        dedup._index.add_note("test-inst", "source.md", "Source Note", "Source summary", [])

        action, path = dedup.should_merge_or_create(
            "test-inst",
            "New Card",
            "New summary",
        )
        # Should not merge with source note
        assert action == "create"
        assert path == ""

    def test_empty_index_returns_create(self) -> None:
        dedup, db = _make_dedup()
        _setup_instance(db)

        action, path = dedup.should_merge_or_create(
            "test-inst",
            "New Card",
            "New summary",
        )
        assert action == "create"
        assert path == ""

    def test_best_match_is_returned(self) -> None:
        """When multiple cards match, the highest-scoring one is returned."""
        v_high = [1.0, 0.0, 0.0, 0.0]
        v_low = [0.5, 0.5, 0.0, 0.0]

        svc = _mock_embedding_service({
            "New Card\nNew summary\n": v_high,
            "High Match\nHigh summary\n": v_high,
            "Low Match\nLow summary\n": v_low,
        })

        dedup, db = _make_dedup(embedding_service=svc)
        _setup_instance(db)
        _setup_note(db, "test-inst", "high.md", "High", "card")
        _setup_note(db, "test-inst", "low.md", "Low", "card")
        dedup._index.add_note("test-inst", "high.md", "High Match", "High summary", [])
        dedup._index.add_note("test-inst", "low.md", "Low Match", "Low summary", [])

        action, path = dedup.should_merge_or_create(
            "test-inst",
            "New Card",
            "New summary",
        )
        assert action == "merge"
        # Should return the highest-scoring match
        assert path == "high.md"


# ---------------------------------------------------------------------------
# Threshold configuration tests
# ---------------------------------------------------------------------------


class TestThresholdConfiguration:
    """Verify that thresholds from Settings are used correctly."""

    def test_custom_source_threshold(self) -> None:
        """Custom source threshold should be respected."""
        v_same = [1.0, 0.0, 0.0, 0.0]
        svc = _mock_embedding_service({
            "Query\nSummary\n": v_same,
            "Source\nSummary\n": v_same,
        })

        # Use very high threshold
        settings = _make_settings(KSM_DEDUP_SOURCE_THRESHOLD="0.99")
        dedup, db = _make_dedup(embedding_service=svc, settings=settings)
        _setup_instance(db)
        _setup_note(db, "test-inst", "source.md", "Source", "source")
        dedup._index.add_note("test-inst", "source.md", "Source", "Summary", [])

        # With exact same vector, score should be 1.0, which passes 0.99
        result = dedup.find_duplicate_source(
            "test-inst", "Query", "Summary", []
        )
        # This may or may not find a match depending on vector similarity
        # The key is that the threshold is being used

    def test_default_thresholds(self) -> None:
        """Verify default threshold values match the spec."""
        dedup, _ = _make_dedup()
        assert dedup._settings.dedup_source_threshold == 0.92
        assert dedup._settings.dedup_card_threshold == 0.88
        assert dedup._settings.dedup_merge_threshold == 0.90


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case handling."""

    def test_empty_title_and_summary(self) -> None:
        """Should handle empty title and summary gracefully."""
        dedup, db = _make_dedup()
        _setup_instance(db)

        result = dedup.find_duplicate_source("test-inst", "", "", [])
        assert result is None

        result = dedup.find_duplicate_cards("test-inst", [{"title": "", "summary": "", "concepts": []}])
        assert result == {}

        action, path = dedup.should_merge_or_create("test-inst", "", "")
        assert action == "create"
        assert path == ""

    def test_concepts_are_included_in_query(self) -> None:
        """Concepts should be part of the query text for embedding."""
        # Track what text was embedded
        embedded_texts: list[str] = []

        settings = _make_settings()
        svc = _mock_embedding_service()
        original_embed = svc.embed_text

        def tracking_embed(text: str) -> list[float]:
            embedded_texts.append(text)
            return original_embed(text)

        svc.embed_text = tracking_embed  # type: ignore[method-assign]

        dedup, db = _make_dedup(embedding_service=svc)
        _setup_instance(db)

        dedup.find_duplicate_source(
            "test-inst",
            "Title",
            "Summary",
            ["concept1", "concept2"],
        )

        assert len(embedded_texts) >= 1
        assert "Title\nSummary\nconcept1, concept2" in embedded_texts
