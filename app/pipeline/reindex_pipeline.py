"""Reindex pipeline — clear and rebuild all indexes for an instance.

Reference: 详细设计文档 Section 9.5
"""

import logging
from pathlib import Path

from app.pipeline.query_dictionary import refresh_instance_dictionary
from app.pipeline.relation_builder import clear_wikilink_cache, compute_concept_overlap_for_instance, extract_all_relations
from app.schema.parser import parse_frontmatter
from app.storage.database import DatabaseBackend
from app.storage.indexer import Indexer
from app.storage.local_backend import LocalStorageBackend

logger = logging.getLogger(__name__)


class ReindexResult:
    """Result of a reindex operation."""

    def __init__(self):
        self.indexed_files: int = 0
        self.relations_count: int = 0
        self.concept_overlaps: int = 0
        self.errors: list[str] = []

    def to_dict(self) -> dict:
        return {
            "indexed_files": self.indexed_files,
            "relations_count": self.relations_count,
            "concept_overlaps": self.concept_overlaps,
            "errors": self.errors,
        }


class ReindexPipeline:
    """Clears and rebuilds all indexes for an instance."""

    def __init__(self, db: DatabaseBackend, storage: LocalStorageBackend, indexer: Indexer):
        self.db = db
        self.storage = storage
        self.indexer = indexer

    def execute(self, instance_id: str, vault_path: str) -> ReindexResult:
        """Full reindex: clear all index data, scan all .md files, rebuild.

        Steps:
        1. Clear all notes, relations, FTS for this instance
        2. Scan all .md files in vault
        3. Parse each file, index note
        4. Extract relations for each file
        5. Compute concept_overlap batch
        """
        result = ReindexResult()

        # Clear wikilink cache to pick up any new/renamed files
        clear_wikilink_cache(vault_path)

        # Step 1: Clear existing index
        self.indexer.clear_instance_index(instance_id)
        logger.info("Cleared index for instance %s", instance_id)

        # Step 2: Scan all .md files
        vault = Path(vault_path)
        md_files = []
        for md_file in vault.rglob("*.md"):
            if ".obsidian" in md_file.parts:
                continue
            md_files.append(md_file)

        # Step 3 & 4: Index each file
        all_relations = []
        for md_file in md_files:
            try:
                rel_path = str(md_file.relative_to(vault)).replace("\\", "/")
                content = md_file.read_text(encoding="utf-8")

                # Index the note
                self.indexer.index_note(instance_id, rel_path, content)
                result.indexed_files += 1

                # Extract relations
                frontmatter, body = parse_frontmatter(content)
                relations = extract_all_relations(body, frontmatter, rel_path, vault_path, self.storage)
                all_relations.extend(relations)
            except Exception as e:
                result.errors.append(f"Error indexing {md_file}: {e}")

        # Index all relations at once
        if all_relations:
            self.indexer.index_relations(instance_id, all_relations)
            result.relations_count = len(all_relations)

        # Step 5: Compute concept_overlap
        try:
            concept_overlaps = compute_concept_overlap_for_instance(instance_id, self.db)
            result.concept_overlaps = concept_overlaps
        except Exception as e:
            result.errors.append(f"Error computing concept_overlap: {e}")

        logger.info(
            "Reindex complete for %s: %d files, %d relations, %d concept_overlaps, %d errors",
            instance_id, result.indexed_files, result.relations_count,
            result.concept_overlaps, len(result.errors),
        )
        refresh_instance_dictionary(instance_id, self.db)

        return result
