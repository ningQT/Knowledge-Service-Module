"""Search service — high-level interface for knowledge search."""

import logging

from app.pipeline.search_pipeline import SearchPipeline
from app.pipeline.search_models import SearchResult
from app.storage.database import DatabaseBackend
from app.storage.filesystem import StorageBackend
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class SearchService:
    """High-level search service wrapping SearchPipeline."""

    def __init__(
        self,
        db: DatabaseBackend,
        storage: StorageBackend | None = None,
        settings: Settings | None = None,
    ):
        self.db = db
        self.storage = storage
        self.settings = settings or get_settings()
        self.pipeline = SearchPipeline(db, storage, self.settings)

    def search(
        self,
        query: str,
        instance_ids: list[str] | None = None,
        layer_filter: int | None = None,
        verification_filter: str | None = None,
        include_comprehension: bool = True,
    ) -> SearchResult:
        """Search knowledge across instances.

        Args:
            query: Natural language search query
            instance_ids: Optional list of instance IDs to search within.
                         If None, searches all instances.
            layer_filter: Optional graph layer filter (1=source, 2=card, 3=map)
            verification_filter: Optional verification status filter

        Returns:
            SearchResult with 4 groups: core_hits, related_cards, source_notes, maps
        """
        return self.pipeline.search_knowledge(
            query,
            instance_ids,
            layer_filter,
            verification_filter,
            include_comprehension=include_comprehension,
        )
