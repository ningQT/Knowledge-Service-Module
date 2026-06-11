"""Service wrapper for answer synthesis."""

from __future__ import annotations

from app.config import Settings
from app.llm.client import LLMClient
from app.pipeline.answer_models import AnswerResult
from app.pipeline.answer_pipeline import AnswerSynthesisPipeline, ProgressCallback
from app.storage.database import DatabaseBackend
from app.storage.filesystem import StorageBackend


class AnswerService:
    """High-level service for map/card driven answer synthesis."""

    def __init__(
        self,
        db: DatabaseBackend,
        storage: StorageBackend,
        llm: LLMClient,
        settings: Settings,
    ):
        self.pipeline = AnswerSynthesisPipeline(db, storage, llm, settings)

    def synthesize(
        self,
        query: str,
        instance_ids: list[str] | None = None,
        *,
        include_search_result: bool = False,
        include_comprehension: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> AnswerResult:
        return self.pipeline.synthesize(
            query=query,
            instance_ids=instance_ids,
            include_search_result=include_search_result,
            include_comprehension=include_comprehension,
            progress_callback=progress_callback,
        )
