"""Tests for semantic dedup integration in WritePipeline."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.llm.embedding import EmbeddingService
from app.storage.sqlite_backend import SQLiteBackend
from app.storage.semantic_index import SemanticIndex


# ---------------------------------------------------------------------------
# Fixtures & helpers (reuse patterns from test_semantic_dedup.py)
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
    """Create an EmbeddingService with mocked API calls."""
    settings = _make_settings()
    svc = EmbeddingService(settings)

    _vectors = vectors or {}

    def _fake_embed(text: str) -> list[float]:
        if text in _vectors:
            return _vectors[text]
        h = hash(text) % 1000
        return [float(h), float(h + 1), float(h + 2), float(h + 3)]

    svc.embed_text = _fake_embed  # type: ignore[method-assign]
    return svc


def _make_index(
    embedding_service: EmbeddingService | None = None,
) -> tuple[SemanticIndex, SQLiteBackend]:
    """Create a SemanticIndex backed by a fresh in-memory SQLite database."""
    db = SQLiteBackend(":memory:", backup_before_migration=False)
    db.init_schema()
    svc = embedding_service or _mock_embedding_service()
    idx = SemanticIndex(db, svc)
    return idx, db


# ---------------------------------------------------------------------------
# WritePipeline.__init__ integration tests
# ---------------------------------------------------------------------------


class TestWritePipelineInit:
    """Verify WritePipeline accepts and stores semantic_index."""

    def test_init_with_no_semantic_index(self) -> None:
        """Default: semantic_index is None, pipeline works without it."""
        from app.pipeline.write_pipeline import WritePipeline

        db = MagicMock()
        storage = MagicMock()
        llm = MagicMock()
        indexer = MagicMock()
        validator = MagicMock()

        pipeline = WritePipeline(db, storage, llm, indexer, validator)
        assert pipeline.semantic_index is None

    def test_init_with_semantic_index(self) -> None:
        """When semantic_index is provided, pipeline stores it."""
        from app.pipeline.write_pipeline import WritePipeline

        db = MagicMock()
        storage = MagicMock()
        llm = MagicMock()
        indexer = MagicMock()
        validator = MagicMock()
        idx, _ = _make_index()

        pipeline = WritePipeline(db, storage, llm, indexer, validator, semantic_index=idx)
        assert pipeline.semantic_index is idx


# ---------------------------------------------------------------------------
# Step 2 semantic dedup integration tests
# ---------------------------------------------------------------------------


class TestStep2SemanticDedup:
    """Verify _step2_path_decision integrates semantic dedup."""

    def _make_pipeline(self, semantic_index: SemanticIndex | None = None):
        from app.pipeline.write_pipeline import WritePipeline

        db = MagicMock()
        storage = MagicMock()
        storage.list_files.return_value = []
        llm = MagicMock()
        indexer = MagicMock()
        validator = MagicMock()
        settings = _make_settings()

        pipeline = WritePipeline(
            db, storage, llm, indexer, validator,
            settings=settings, semantic_index=semantic_index,
        )
        return pipeline

    def test_step2_skips_dedup_when_no_index(self) -> None:
        """When semantic_index is None, step 2 should not crash."""
        pipeline = self._make_pipeline(semantic_index=None)
        pipeline._current_instance_id = "test-inst"

        from app.llm.schemas import DocClassification, PathDecision

        classification = DocClassification(
            doc_type="article", domain="AI", kind="concept", topics=["test"]
        )
        # Mock the LLM call to return a path decision
        mock_decision = PathDecision(
            source_name="test-source",
            existing_source=None,
            candidate_cards=["card1"],
        )
        with patch.object(pipeline, "_run_structured_agent", return_value=mock_decision):
            result = pipeline._step2_path_decision(
                "test.md", classification, "/tmp/vault"
            )

        assert result.source_name == "test-source"
        assert result.existing_source is None

    def test_step2_sets_existing_source_when_duplicate_found(self) -> None:
        """When a duplicate source is found, existing_source is set."""
        idx, db = _make_index()
        _setup_instance(db, "test-inst")

        # Add a source note to the index
        svc = _mock_embedding_service()
        idx_with_svc = SemanticIndex(db, svc)
        svc.embed_text = lambda text: [1.0, 0.0, 0.0, 0.0]  # type: ignore[method-assign]
        idx_with_svc.add_note("test-inst", "01-资料来源/ExistingSource.md", "Existing Source", "A source", ["topic1"])
        _setup_note(db, "test-inst", "01-资料来源/ExistingSource.md", "Existing Source", "source")

        pipeline = self._make_pipeline(semantic_index=idx_with_svc)
        pipeline._current_instance_id = "test-inst"

        from app.llm.schemas import DocClassification, PathDecision

        classification = DocClassification(
            doc_type="article", domain="AI", kind="concept", topics=["topic1"]
        )
        mock_decision = PathDecision(
            source_name="ExistingSource",
            existing_source=None,
            candidate_cards=["card1"],
        )
        with patch.object(pipeline, "_run_structured_agent", return_value=mock_decision):
            result = pipeline._step2_path_decision(
                "test.md", classification, "/tmp/vault"
            )

        # existing_source should be set to the duplicate path
        assert result.existing_source == "01-资料来源/ExistingSource.md"

    def test_step2_does_not_override_existing_source(self) -> None:
        """When existing_source is already set by LLM, semantic dedup doesn't override."""
        idx, db = _make_index()
        _setup_instance(db, "test-inst")

        svc = _mock_embedding_service()
        idx_with_svc = SemanticIndex(db, svc)
        svc.embed_text = lambda text: [1.0, 0.0, 0.0, 0.0]  # type: ignore[method-assign]
        idx_with_svc.add_note("test-inst", "01-资料来源/Dup.md", "Dup", "dup", ["topic1"])
        _setup_note(db, "test-inst", "01-资料来源/Dup.md", "Dup", "source")

        pipeline = self._make_pipeline(semantic_index=idx_with_svc)
        pipeline._current_instance_id = "test-inst"

        from app.llm.schemas import DocClassification, PathDecision

        classification = DocClassification(
            doc_type="article", domain="AI", kind="concept", topics=["topic1"]
        )
        mock_decision = PathDecision(
            source_name="NewSource",
            existing_source="01-资料来源/Original.md",  # Already set by LLM
            candidate_cards=["card1"],
        )
        with patch.object(pipeline, "_run_structured_agent", return_value=mock_decision):
            result = pipeline._step2_path_decision(
                "test.md", classification, "/tmp/vault"
            )

        # Should keep the LLM's existing_source, not override with dedup result
        assert result.existing_source == "01-资料来源/Original.md"


# ---------------------------------------------------------------------------
# Step 4 semantic dedup filtering tests
# ---------------------------------------------------------------------------


class TestStep4SemanticDedup:
    """Verify _phase2_knowledge_locate filters duplicates."""

    def _make_pipeline(self, semantic_index: SemanticIndex | None = None):
        from app.pipeline.write_pipeline import WritePipeline

        db = MagicMock()
        storage = MagicMock()
        storage.list_files.return_value = []
        llm = MagicMock()
        indexer = MagicMock()
        validator = MagicMock()
        settings = _make_settings()

        pipeline = WritePipeline(
            db, storage, llm, indexer, validator,
            settings=settings, semantic_index=semantic_index,
        )
        return pipeline

    def test_step4_rejects_similar_knowledge_points(self) -> None:
        """Knowledge points similar to existing notes should be rejected."""
        idx, db = _make_index()
        _setup_instance(db, "test-inst")

        # Use a vector dict: "Existing Card" query matches stored vector, "New Unique Point" doesn't
        existing_vec = [1.0, 0.0, 0.0, 0.0]
        unique_vec = [0.0, 0.0, 1.0, 0.0]  # orthogonal, won't match

        vectors = {
            # The stored note's embedding
            "Existing Card\nexisting\nconcept": existing_vec,
            # The query for "Existing Card" knowledge point (similar to stored)
            "Existing Card\nExisting Card": existing_vec,
            # The query for "New Unique Point" (different from stored)
            "New Unique Point\nNew Unique Point": unique_vec,
        }
        svc = _mock_embedding_service(vectors)
        idx_with_svc = SemanticIndex(db, svc)
        idx_with_svc.add_note("test-inst", "02-知识卡片/ExistingCard.md", "Existing Card", "existing", ["concept"])
        _setup_note(db, "test-inst", "02-知识卡片/ExistingCard.md", "Existing Card", "card")

        pipeline = self._make_pipeline(semantic_index=idx_with_svc)
        pipeline._current_instance_id = "test-inst"

        from app.llm.schemas import DocClassification, KnowledgeLocateResult, KnowledgePoint, PathDecision

        classification = DocClassification(
            doc_type="article", domain="AI", kind="concept", topics=["concept"]
        )
        path_decision = PathDecision(
            source_name="source", existing_source=None, candidate_cards=["card1"]
        )

        # Mock LLM to return knowledge points
        locate_result = KnowledgeLocateResult(
            knowledge_points=[
                KnowledgePoint(name="Existing Card", section_id=1, section_title="Existing Card", estimated_tokens=100),
                KnowledgePoint(name="New Unique Point", section_id=2, section_title="New Unique Point", estimated_tokens=100),
            ],
            total_points=2,
        )
        with patch.object(pipeline, "_run_structured_agent", return_value=locate_result):
            result = pipeline._phase2_knowledge_locate(
                "content", MagicMock(headings=[]), classification, path_decision, "/tmp/vault", ""
            )

        # "Existing Card" should be rejected, "New Unique Point" should remain
        assert len(result.knowledge_points) == 1
        assert result.knowledge_points[0].name == "New Unique Point"
        assert "Existing Card" in result.rejected

    def test_step4_skips_dedup_when_no_index(self) -> None:
        """When semantic_index is None, step 4 should not filter anything."""
        pipeline = self._make_pipeline(semantic_index=None)
        pipeline._current_instance_id = "test-inst"

        from app.llm.schemas import DocClassification, KnowledgeLocateResult, KnowledgePoint, PathDecision

        classification = DocClassification(
            doc_type="article", domain="AI", kind="concept", topics=["concept"]
        )
        path_decision = PathDecision(
            source_name="source", existing_source=None, candidate_cards=["card1"]
        )

        locate_result = KnowledgeLocateResult(
            knowledge_points=[
                KnowledgePoint(name="Point1", section_id=1, section_title="Point1", estimated_tokens=100),
                KnowledgePoint(name="Point2", section_id=2, section_title="Point2", estimated_tokens=100),
            ],
            total_points=2,
        )
        with patch.object(pipeline, "_run_structured_agent", return_value=locate_result):
            result = pipeline._phase2_knowledge_locate(
                "content", MagicMock(headings=[]), classification, path_decision, "/tmp/vault", ""
            )

        # No filtering when semantic_index is None
        assert len(result.knowledge_points) == 2
        assert len(result.rejected) == 0


# ---------------------------------------------------------------------------
# Step 5 merge/create tests
# ---------------------------------------------------------------------------


class TestStep5MergeOrCreate:
    """Verify _generate_cards_from_points integrates merge/create logic."""

    def test_merge_updates_existing_card(self) -> None:
        """When merge decision is returned, existing card is updated."""
        from app.pipeline.write_pipeline import WritePipeline

        db = MagicMock()
        storage = MagicMock()
        llm = MagicMock()
        indexer = MagicMock()
        validator = MagicMock()
        settings = _make_settings()

        idx, real_db = _make_index()
        _setup_instance(real_db, "test-inst")

        # Set up semantic index to return a merge decision
        svc = _mock_embedding_service()
        idx_with_svc = SemanticIndex(real_db, svc)
        svc.embed_text = lambda text: [1.0, 0.0, 0.0, 0.0]  # type: ignore[method-assign]
        idx_with_svc.add_note("test-inst", "02-知识卡片/ExistingCard.md", "Existing Card", "existing", ["concept1"])
        _setup_note(real_db, "test-inst", "02-知识卡片/ExistingCard.md", "Existing Card", "card")

        pipeline = WritePipeline(
            db, storage, llm, indexer, validator,
            settings=settings, semantic_index=idx_with_svc,
        )
        pipeline._current_instance_id = "test-inst"

        # Mock storage to return existing card content
        existing_fm = (
            "---\ntype: card\nsources:\n  - 01-资料来源/OldSource.md\nconcepts:\n  - concept1\n---\n\n# Existing Card\n\nOld content."
        )
        storage.read_file.return_value = existing_fm

        from app.llm.schemas import CardOutput, DocClassification, KnowledgePointOutput

        classification = DocClassification(
            doc_type="article", domain="AI", kind="concept", topics=["concept1"]
        )
        point = KnowledgePointOutput(
            card_title="Existing Card",
            section_id=1,
            para_range=[0, 100],
            concepts=["concept1"],
            role="concept",
            extraction_confidence="medium",
        )

        # Mock LLM to return card output
        card_output = CardOutput(
            title="Existing Card",
            summary="Updated summary",
            concepts=["concept1", "concept2"],
            sections=[],
            relations="",
            sources_text="",
            wikilinks=[],
            graph_role="concept",
        )

        from unittest.mock import AsyncMock

        mock_run = MagicMock()
        mock_run.output = card_output
        mock_run.truncated = False

        with patch.object(pipeline, "_run_structured_agent_result", return_value=mock_run):
            with patch.object(pipeline, "_validate_card_quality", return_value=([], [])):
                with patch.object(pipeline, "_collect_existing_card_names", return_value=set()):
                    with patch("app.pipeline.write_pipeline.parse_frontmatter") as mock_parse:
                        mock_parse.return_value = (
                            {
                                "type": "card",
                                "sources": ["01-资料来源/OldSource.md"],
                                "concepts": ["concept1"],
                            },
                            "# Existing Card\n\nOld content.",
                        )
                        with patch("app.pipeline.write_pipeline.serialize_frontmatter") as mock_serialize:
                            mock_serialize.return_value = "updated-content"
                            card_paths, card_contents = pipeline._generate_cards_from_points(
                                "/tmp/vault",
                                "content",
                                None,
                                classification,
                                [point],
                                "01-资料来源/NewSource.md",
                                fast_context="context",
                            )

        # Card should be merged into existing path
        assert len(card_paths) == 1
        assert card_paths[0] == "02-知识卡片/ExistingCard.md"

    def test_create_proceeds_normally(self) -> None:
        """When create decision is returned, new card is created."""
        from app.pipeline.write_pipeline import WritePipeline

        db = MagicMock()
        storage = MagicMock()
        llm = MagicMock()
        indexer = MagicMock()
        validator = MagicMock()
        settings = _make_settings()

        # Use index that returns no similar cards (create decision)
        idx, real_db = _make_index()
        _setup_instance(real_db, "test-inst")

        pipeline = WritePipeline(
            db, storage, llm, indexer, validator,
            settings=settings, semantic_index=idx,
        )
        pipeline._current_instance_id = "test-inst"

        from app.llm.schemas import CardOutput, DocClassification, KnowledgePointOutput

        classification = DocClassification(
            doc_type="article", domain="AI", kind="concept", topics=["concept1"]
        )
        point = KnowledgePointOutput(
            card_title="New Card",
            section_id=1,
            para_range=[0, 100],
            concepts=["concept1"],
            role="concept",
            extraction_confidence="medium",
        )

        card_output = CardOutput(
            title="New Card",
            summary="New card summary",
            concepts=["concept1"],
            sections=[],
            relations="",
            sources_text="",
            wikilinks=[],
            graph_role="concept",
        )

        mock_run = MagicMock()
        mock_run.output = card_output
        mock_run.truncated = False

        with patch.object(pipeline, "_run_structured_agent_result", return_value=mock_run):
            with patch.object(pipeline, "_validate_card_quality", return_value=([], [])):
                with patch.object(pipeline, "_collect_existing_card_names", return_value=set()):
                    with patch("app.pipeline.write_pipeline.serialize_frontmatter") as mock_serialize:
                        mock_serialize.return_value = "new-card-content"
                        card_paths, card_contents = pipeline._generate_cards_from_points(
                            "/tmp/vault",
                            "content",
                            None,
                            classification,
                            [point],
                            "01-资料来源/Source.md",
                            fast_context="context",
                        )

        # New card should be created
        assert len(card_paths) == 1
        assert "New Card" in card_paths[0]


# ---------------------------------------------------------------------------
# Step 8 semantic index update tests
# ---------------------------------------------------------------------------


class TestStep8SemanticIndexUpdate:
    """Verify _step8_archive_and_index updates semantic index."""

    def test_step8_updates_semantic_index_for_cards_and_map(self) -> None:
        """After indexing, semantic index is updated for each card and map."""
        from app.pipeline.write_pipeline import WritePipeline

        idx, db = _make_index()
        _setup_instance(db, "test-inst")

        storage = MagicMock()
        storage.read_file.return_value = map_fm = (
            "---\ntype: map\ntitle: Test Map\nconcepts:\n  - concept1\n---\n\n# Test Map\n\nBody."
        )

        pipeline = WritePipeline(
            MagicMock(), storage, MagicMock(), MagicMock(), MagicMock(),
            semantic_index=idx,
        )

        card_fm = "---\ntype: card\ntitle: Test Card\nconcepts:\n  - concept1\n---\n\n# Test Card\n\nBody."

        result = MagicMock()
        result.status = "success"

        pipeline._step8_archive_and_index(
            instance_id="test-inst",
            vault_path="/tmp/vault",
            source_path="01-资料来源/source.md",
            source_content="---\ntype: source\ndoc_title: Source\ndoc_summary: Summary\nconcepts:\n  - c1\n---\n\nBody.",
            card_paths=["02-知识卡片/TestCard.md"],
            card_contents=[card_fm],
            map_path="03-知识地图/TestMap.md",
            result=result,
            now="2024-01-01T00:00:00",
        )

        # Verify semantic index has embeddings for card, map, and source
        rows = db.execute(
            "SELECT file_path FROM note_embeddings WHERE instance_id = ?",
            ("test-inst",),
        )
        paths = {r["file_path"] for r in rows}
        assert "02-知识卡片/TestCard.md" in paths
        assert "03-知识地图/TestMap.md" in paths
        assert "01-资料来源/source.md" in paths

    def test_step8_skips_semantic_index_when_none(self) -> None:
        """When semantic_index is None, step 8 should not crash."""
        from app.pipeline.write_pipeline import WritePipeline

        storage = MagicMock()
        storage.read_file.return_value = (
            "---\ntype: map\n---\n\nBody."
        )

        pipeline = WritePipeline(
            MagicMock(), storage, MagicMock(), MagicMock(), MagicMock(),
            semantic_index=None,
        )

        result = MagicMock()
        result.status = "success"

        # Should not raise
        pipeline._step8_archive_and_index(
            instance_id="test-inst",
            vault_path="/tmp/vault",
            source_path="01-资料来源/source.md",
            source_content="---\ntype: source\n---\n\nBody.",
            card_paths=[],
            card_contents=[],
            map_path=None,
            result=result,
            now="2024-01-01T00:00:00",
        )
