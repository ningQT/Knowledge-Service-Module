"""Tests for WritePipeline fixes: dedup caching, summary threading, create log."""

from __future__ import annotations

import logging
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.llm.embedding import EmbeddingService
from app.storage.sqlite_backend import SQLiteBackend
from app.storage.semantic_index import SemanticIndex


# ---------------------------------------------------------------------------
# Fixtures & helpers (reused from test_write_pipeline_dedup.py)
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
# Issue 1: _step2_path_decision passes source_content as summary
# ---------------------------------------------------------------------------


class TestStep2SummaryThreading:
    """Verify _step2_path_decision passes source_content to find_duplicate_source."""

    def test_step2_passes_truncated_content_as_summary(self) -> None:
        """The source_content parameter should be truncated to 500 chars and passed as summary."""
        idx, db = _make_index()
        _setup_instance(db, "test-inst")

        svc = _mock_embedding_service()
        idx_with_svc = SemanticIndex(db, svc)
        svc.embed_text = lambda text: [1.0, 0.0, 0.0, 0.0]  # type: ignore[method-assign]
        idx_with_svc.add_note(
            "test-inst", "01-资料来源/ExistingSource.md",
            "Existing Source", "A source", ["topic1"],
        )
        _setup_note(db, "test-inst", "01-资料来源/ExistingSource.md", "Existing Source", "source")

        from app.pipeline.write_pipeline import WritePipeline

        db_mock = MagicMock()
        storage_mock = MagicMock()
        storage_mock.list_files.return_value = []
        pipeline = WritePipeline(
            db_mock, storage_mock, MagicMock(), MagicMock(), MagicMock(),
            settings=_make_settings(), semantic_index=idx_with_svc,
        )
        pipeline._current_instance_id = "test-inst"

        from app.llm.schemas import DocClassification, PathDecision

        classification = DocClassification(
            doc_type="article", domain="AI", kind="concept", topics=["topic1"],
        )
        mock_decision = PathDecision(
            source_name="ExistingSource",
            existing_source=None,
            candidate_cards=["card1"],
        )

        long_content = "A" * 1000  # Content longer than 500 chars

        with patch.object(pipeline, "_run_structured_agent", return_value=mock_decision):
            with patch(
                "app.pipeline.write_pipeline.truncate_with_marker",
                wraps=__import__("app.shared_infra.truncation", fromlist=["truncate_with_marker"]).truncate_with_marker,
            ) as mock_truncate:
                result = pipeline._step2_path_decision(
                    "test.md", classification, "/tmp/vault",
                    source_content=long_content,
                )

        # truncate_with_marker should have been called with the long content
        mock_truncate.assert_called()
        # The first call should be with source_content and max 500
        first_call_args = mock_truncate.call_args_list[0]
        assert first_call_args[0][0] == long_content
        assert first_call_args[0][1] == 500

    def test_step2_accepts_source_content_parameter(self) -> None:
        """_step2_path_decision should accept source_content parameter without error."""
        from app.pipeline.write_pipeline import WritePipeline

        storage_mock = MagicMock()
        storage_mock.list_files.return_value = []
        pipeline = WritePipeline(
            MagicMock(), storage_mock, MagicMock(), MagicMock(), MagicMock(),
            settings=_make_settings(),
        )
        pipeline._current_instance_id = None  # No semantic index

        from app.llm.schemas import DocClassification, PathDecision

        classification = DocClassification(
            doc_type="article", domain="AI", kind="concept", topics=["test"],
        )
        mock_decision = PathDecision(
            source_name="test-source", existing_source=None, candidate_cards=["card1"],
        )

        with patch.object(pipeline, "_run_structured_agent", return_value=mock_decision):
            result = pipeline._step2_path_decision(
                "test.md", classification, "/tmp/vault",
                source_content="Some source content",
            )

        assert result.source_name == "test-source"


# ---------------------------------------------------------------------------
# Issue 2: SemanticDeduplicator is cached and reused
# ---------------------------------------------------------------------------


class TestDedupCaching:
    """Verify SemanticDeduplicator is cached on WritePipeline instance."""

    def test_get_deduplicator_returns_same_instance(self) -> None:
        """_get_deduplicator should return the same instance on repeated calls."""
        idx, db = _make_index()
        _setup_instance(db, "test-inst")

        from app.pipeline.write_pipeline import WritePipeline

        pipeline = WritePipeline(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
            settings=_make_settings(), semantic_index=idx,
        )

        dedup1 = pipeline._get_deduplicator()
        dedup2 = pipeline._get_deduplicator()

        assert dedup1 is dedup2
        assert pipeline._dedup is dedup1

    def test_get_deduplicator_returns_none_when_no_index(self) -> None:
        """_get_deduplicator should return None when semantic_index is None."""
        from app.pipeline.write_pipeline import WritePipeline

        pipeline = WritePipeline(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
            settings=_make_settings(), semantic_index=None,
        )

        dedup = pipeline._get_deduplicator()
        assert dedup is None

    def test_dedup_cached_in_step2(self) -> None:
        """Step 2 should use the cached deduplicator instead of creating a new one."""
        idx, db = _make_index()
        _setup_instance(db, "test-inst")

        from app.pipeline.write_pipeline import WritePipeline

        storage_mock = MagicMock()
        storage_mock.list_files.return_value = []
        pipeline = WritePipeline(
            MagicMock(), storage_mock, MagicMock(), MagicMock(), MagicMock(),
            settings=_make_settings(), semantic_index=idx,
        )
        pipeline._current_instance_id = "test-inst"

        from app.llm.schemas import DocClassification, PathDecision

        classification = DocClassification(
            doc_type="article", domain="AI", kind="concept", topics=["test"],
        )
        mock_decision = PathDecision(
            source_name="test-source", existing_source=None, candidate_cards=["card1"],
        )

        with patch.object(pipeline, "_run_structured_agent", return_value=mock_decision):
            pipeline._step2_path_decision(
                "test.md", classification, "/tmp/vault",
                source_content="content",
            )

        # After step 2, _dedup should be populated
        assert pipeline._dedup is not None

        # Second call should reuse the same instance
        first_dedup = pipeline._dedup
        with patch.object(pipeline, "_run_structured_agent", return_value=mock_decision):
            pipeline._step2_path_decision(
                "test.md", classification, "/tmp/vault",
                source_content="content",
            )
        assert pipeline._dedup is first_dedup

    def test_dedup_cached_in_step5(self) -> None:
        """Step 5 card generation should use the cached deduplicator."""
        idx, db = _make_index()
        _setup_instance(db, "test-inst")

        from app.pipeline.write_pipeline import WritePipeline

        pipeline = WritePipeline(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
            settings=_make_settings(), semantic_index=idx,
        )
        pipeline._current_instance_id = "test-inst"

        from app.llm.schemas import (
            CardOutput, DocClassification, KnowledgePointOutput,
        )

        classification = DocClassification(
            doc_type="article", domain="AI", kind="concept", topics=["c1"],
        )
        point = KnowledgePointOutput(
            card_title="Test Card",
            section_id=1,
            para_range=[0, 100],
            concepts=["c1"],
            role="concept",
            extraction_confidence="medium",
        )
        card_output = CardOutput(
            title="Test Card",
            summary="Summary",
            concepts=["c1"],
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
                    with patch("app.pipeline.write_pipeline.serialize_frontmatter") as mock_ser:
                        mock_ser.return_value = "card-content"
                        pipeline._generate_cards_from_points(
                            "/tmp/vault", "content", None,
                            classification, [point], "src.md",
                            fast_context="ctx",
                        )

        # After step 5, _dedup should be populated
        assert pipeline._dedup is not None


# ---------------------------------------------------------------------------
# Issue 3: "create" action log in step 5
# ---------------------------------------------------------------------------


class TestStep5CreateLog:
    """Verify the "create" action is logged in step 5."""

    def test_create_action_emits_log(self) -> None:
        """When dedup_action is 'create', a log message should be emitted."""
        idx, db = _make_index()
        _setup_instance(db, "test-inst")

        from app.pipeline.write_pipeline import WritePipeline

        pipeline = WritePipeline(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
            settings=_make_settings(), semantic_index=idx,
        )
        pipeline._current_instance_id = "test-inst"

        from app.llm.schemas import (
            CardOutput, DocClassification, KnowledgePointOutput,
        )

        classification = DocClassification(
            doc_type="article", domain="AI", kind="concept", topics=["c1"],
        )
        point = KnowledgePointOutput(
            card_title="New Unique Card",
            section_id=1,
            para_range=[0, 100],
            concepts=["c1"],
            role="concept",
            extraction_confidence="medium",
        )
        card_output = CardOutput(
            title="New Unique Card",
            summary="A brand new card",
            concepts=["c1"],
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
                    with patch("app.pipeline.write_pipeline.serialize_frontmatter") as mock_ser:
                        mock_ser.return_value = "card-content"
                        with patch("app.pipeline.write_pipeline.logger") as mock_logger:
                            pipeline._generate_cards_from_points(
                                "/tmp/vault", "content", None,
                                classification, [point], "src.md",
                                fast_context="ctx",
                            )

        # Verify the create log was emitted
        create_calls = [
            call for call in mock_logger.info.call_args_list
            if "creating new card" in str(call)
        ]
        assert len(create_calls) >= 1, (
            f"Expected 'creating new card' log, got info calls: {mock_logger.info.call_args_list}"
        )
        # Verify the card title is in the log message
        assert "New Unique Card" in str(create_calls[0])


# ---------------------------------------------------------------------------
# Issue 4: TODO comment in indexer.py
# ---------------------------------------------------------------------------


class TestIndexerTodoComment:
    """Verify the TODO comment about orphaned embeddings is present."""

    def test_remove_note_has_todo_comment(self) -> None:
        """The remove_note method should have a TODO comment about orphaned embeddings."""
        import inspect
        from app.storage.indexer import Indexer

        source = inspect.getsource(Indexer.remove_note)
        assert "TODO" in source
        assert "note_embeddings" in source
        assert "orphaned" in source.lower()
