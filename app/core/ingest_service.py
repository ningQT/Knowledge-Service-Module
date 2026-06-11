"""Ingest service - entry point for document ingestion."""

import json
import logging
from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.exceptions import IngestFailedError, InstanceNotFoundError
from app.llm.client import LLMClient
from app.pipeline.write_pipeline import IngestResult, WritePipeline
from app.schema.validator import SchemaValidator
from app.storage.database import DatabaseBackend
from app.storage.filesystem import StorageBackend
from app.storage.indexer import Indexer

logger = logging.getLogger(__name__)


class IngestService:
    """Handles document ingestion into knowledge base.

    Reference: 详细设计文档 Section 6
    """

    def __init__(
        self,
        db: DatabaseBackend,
        storage: StorageBackend,
        llm: LLMClient,
        settings: Settings,
        indexer: Indexer | None = None,
    ):
        self.db = db
        self.storage = storage
        self.llm = llm
        self.settings = settings
        self.indexer = indexer or Indexer(db)
        self.validator = SchemaValidator()

    def ingest_document(
        self,
        instance_id: str,
        file_path: str,
        filename: str | None = None,
        auto_map: bool | None = True,
        domain_hint: str | None = None,
        progress_callback: Callable[[int, str, dict | None], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        job_id: str | None = None,
    ) -> IngestResult:
        """Ingest a markdown document into a knowledge base instance.

        1. Validate instance exists
        2. Read the document
        3. Run the write pipeline
        """
        # Validate instance
        instances = self.db.execute(
            "SELECT id, vault_path, auto_map, config_json FROM instances WHERE id = ?",
            (instance_id,),
        )
        if not instances:
            raise InstanceNotFoundError(instance_id)

        instance = instances[0]
        vault_path = instance["vault_path"]
        language = _instance_language(instance.get("config_json"))
        if auto_map is None:
            auto_map = bool(instance.get("auto_map", True))

        # Read document
        if not filename:
            filename = Path(file_path).name

        try:
            markdown = self.storage.read_file(file_path)
        except Exception:
            # Try as absolute path
            try:
                with open(file_path, encoding="utf-8") as f:
                    markdown = f.read()
            except Exception as e:
                raise IngestFailedError(f"Cannot read file: {e}")

        # Run pipeline
        pipeline = WritePipeline(
            db=self.db,
            storage=self.storage,
            llm=self.llm,
            indexer=self.indexer,
            validator=self.validator,
            settings=self.settings,
        )

        result = pipeline.execute(
            instance_id=instance_id,
            vault_path=vault_path,
            markdown=markdown,
            filename=filename,
            domain_hint=domain_hint,
            auto_map=auto_map,
            language=language,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            job_id=job_id,
        )

        if result.status == "failed":
            raise IngestFailedError("; ".join(result.warnings))

        return result


def _instance_language(config_json: object) -> str:
    if isinstance(config_json, str) and config_json.strip():
        try:
            config = json.loads(config_json)
        except json.JSONDecodeError:
            config = {}
    elif isinstance(config_json, dict):
        config = config_json
    else:
        config = {}
    language = str(config.get("language") or "zh").strip().lower()
    return language if language in {"zh", "en"} else "zh"
