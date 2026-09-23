"""Semantic deduplication decision maker for the KSM write pipeline.

Uses SemanticIndex for cosine-similarity search to detect duplicate notes
and decide whether to merge or create new cards.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings, get_settings
from app.storage.semantic_index import SemanticIndex

logger = logging.getLogger(__name__)


class SemanticDeduplicator:
    """Makes deduplication decisions by querying the semantic index.

    Provides three core operations:
    - find_duplicate_source: strict check for duplicate source notes (0.92)
    - find_duplicate_cards: batch check for duplicate cards (0.88)
    - should_merge_or_create: decision logic for card merge vs create (0.90)
    """

    def __init__(
        self,
        semantic_index: SemanticIndex,
        settings: Settings | None = None,
    ) -> None:
        """Initialize the deduplicator.

        Args:
            semantic_index: The semantic index for similarity searches.
            settings: Application settings. If None, loads from get_settings().
        """
        self._index = semantic_index
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_duplicate_source(
        self,
        instance_id: str,
        new_title: str,
        new_summary: str,
        new_concepts: list[str],
    ) -> str | None:
        """Search for an existing source note that is a duplicate.

        Uses a strict threshold (0.92) to avoid false positives.

        Args:
            instance_id: The vault instance ID.
            new_title: Title of the new source note.
            new_summary: Summary of the new source note.
            new_concepts: List of concept tags.

        Returns:
            The file_path of the duplicate source note if found, else None.
        """
        query_text = self._build_query_text(new_title, new_summary, new_concepts)
        threshold = self._settings.dedup_source_threshold

        results = self._index.find_similar(
            instance_id,
            query_text,
            threshold=threshold,
            top_k=5,
        )

        # Filter to source notes only
        for result in results:
            if result.get("type") == "source":
                logger.info(
                    "Found duplicate source: %s (score=%.4f)",
                    result["file_path"],
                    result["score"],
                )
                return result["file_path"]

        return None

    def find_duplicate_cards(
        self,
        instance_id: str,
        candidate_cards: list[dict[str, Any]],
    ) -> dict[str, str]:
        """Batch search for duplicate cards among candidates.

        For each candidate card, searches for similar existing cards
        using a relaxed threshold (0.88).

        Args:
            instance_id: The vault instance ID.
            candidate_cards: List of dicts with keys:
                - title: Card title
                - summary: Card summary
                - concepts: List of concept tags (optional)

        Returns:
            Dict mapping card_title -> existing_file_path for duplicates.
            Cards without duplicates are not included.
        """
        threshold = self._settings.dedup_card_threshold
        duplicates: dict[str, str] = {}

        for card in candidate_cards:
            title = card.get("title", "")
            summary = card.get("summary", "")
            concepts = card.get("concepts", [])

            query_text = self._build_query_text(title, summary, concepts)

            results = self._index.find_similar(
                instance_id,
                query_text,
                threshold=threshold,
                top_k=5,
            )

            # Filter to card notes only
            for result in results:
                if result.get("type") == "card":
                    logger.info(
                        "Found duplicate card '%s': %s (score=%.4f)",
                        title,
                        result["file_path"],
                        result["score"],
                    )
                    duplicates[title] = result["file_path"]
                    break  # Take the best match for this card

        return duplicates

    def should_merge_or_create(
        self,
        instance_id: str,
        new_card_title: str,
        new_card_summary: str,
    ) -> tuple[str, str]:
        """Decide whether to merge with an existing card or create a new one.

        Uses a medium threshold (0.90) for the merge decision.

        Args:
            instance_id: The vault instance ID.
            new_card_title: Title of the new card.
            new_card_summary: Summary of the new card.

        Returns:
            A tuple of (action, file_path) where:
            - action is "merge" or "create"
            - file_path is the path to merge with (if action="merge"), else ""
        """
        query_text = self._build_query_text(new_card_title, new_card_summary, [])
        threshold = self._settings.dedup_merge_threshold

        results = self._index.find_similar(
            instance_id,
            query_text,
            threshold=threshold,
            top_k=5,
        )

        # Filter to card notes only and return the best match
        for result in results:
            if result.get("type") == "card":
                logger.info(
                    "Merge decision for '%s': merge with %s (score=%.4f)",
                    new_card_title,
                    result["file_path"],
                    result["score"],
                )
                return ("merge", result["file_path"])

        logger.info(
            "Merge decision for '%s': create new card",
            new_card_title,
        )
        return ("create", "")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_query_text(title: str, summary: str, concepts: list[str]) -> str:
        """Build query text from note metadata for embedding.

        Uses the same format as SemanticIndex._build_embed_text for consistency.
        """
        concept_str = ", ".join(concepts) if concepts else ""
        parts = [title, summary, concept_str]
        return "\n".join(parts)
