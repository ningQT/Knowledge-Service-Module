"""Sync pipeline — detect filesystem changes and incrementally update index.

Reference: 详细设计文档 Section 8.5 (增量重索引规则)
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.pipeline.query_dictionary import refresh_instance_dictionary
from app.pipeline.relation_builder import clear_wikilink_cache, extract_all_relations
from app.schema.parser import parse_frontmatter
from app.storage.database import DatabaseBackend
from app.storage.indexer import Indexer
from app.storage.local_backend import LocalStorageBackend

logger = logging.getLogger(__name__)


class SyncResult:
    """Result of a sync operation."""

    def __init__(self):
        self.added: list[str] = []
        self.modified: list[str] = []
        self.deleted: list[str] = []
        self.errors: list[str] = []

    @property
    def total_changes(self) -> int:
        return len(self.added) + len(self.modified) + len(self.deleted)

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "modified": self.modified,
            "deleted": self.deleted,
            "errors": self.errors,
            "total_changes": self.total_changes,
        }


class SyncPipeline:
    """Detects filesystem changes and incrementally updates the index."""

    def __init__(self, db: DatabaseBackend, storage: LocalStorageBackend, indexer: Indexer):
        self.db = db
        self.storage = storage
        self.indexer = indexer

    def execute(self, instance_id: str, vault_path: str) -> SyncResult:
        """Run sync: compare filesystem vs index, apply changes.

        Steps:
        1. Scan all .md files in vault
        2. Compare with notes table (by file_path + content_hash)
        3. Detect added / modified / deleted files
        4. For added/modified: re-parse, update index, update relations
        5. For deleted: remove from index
        """
        result = SyncResult()

        # Clear wikilink cache to pick up any new/renamed files
        clear_wikilink_cache(vault_path)

        # Get indexed files with their content hashes
        indexed = self._get_indexed_files(instance_id)
        indexed_paths = set(indexed.keys())

        # Scan filesystem
        fs_files = self._scan_md_files(vault_path)
        fs_relative_paths = set(fs_files.keys())

        # Detect changes
        added = fs_relative_paths - indexed_paths
        deleted = indexed_paths - fs_relative_paths
        common = fs_relative_paths & indexed_paths

        modified = set()
        for rel_path in common:
            abs_path = fs_files[rel_path]
            try:
                content = abs_path.read_text(encoding="utf-8")
                current_hash = hashlib.md5(content.encode()).hexdigest()
                if current_hash != indexed[rel_path]:
                    modified.add(rel_path)
            except Exception as e:
                result.errors.append(f"Error reading {rel_path}: {e}")

        # Process additions
        for rel_path in added:
            try:
                abs_path = fs_files[rel_path]
                content = abs_path.read_text(encoding="utf-8")
                self.indexer.index_note(instance_id, rel_path, content)
                # Extract and index relations
                self._index_file_relations(instance_id, rel_path, content, vault_path)
                result.added.append(rel_path)
            except Exception as e:
                result.errors.append(f"Error adding {rel_path}: {e}")

        # Process modifications
        for rel_path in modified:
            try:
                abs_path = fs_files[rel_path]
                content = abs_path.read_text(encoding="utf-8")
                # Remove old relations first
                self.db.execute(
                    "DELETE FROM relations WHERE instance_id = ? AND source_path = ?",
                    (instance_id, rel_path),
                )
                self.indexer.index_note(instance_id, rel_path, content)
                self._index_file_relations(instance_id, rel_path, content, vault_path)
                result.modified.append(rel_path)
            except Exception as e:
                result.errors.append(f"Error modifying {rel_path}: {e}")

        # Process deletions
        for rel_path in deleted:
            try:
                self.indexer.remove_note(instance_id, rel_path)
                result.deleted.append(rel_path)
            except Exception as e:
                result.errors.append(f"Error deleting {rel_path}: {e}")

        logger.info(
            "Sync complete for %s: +%d ~%d -%d errors=%d",
            instance_id, len(result.added), len(result.modified),
            len(result.deleted), len(result.errors),
        )
        if result.total_changes:
            refresh_instance_dictionary(instance_id, self.db)

        return result

    def _get_indexed_files(self, instance_id: str) -> dict[str, str]:
        """Get indexed file paths and their content hashes."""
        rows = self.db.execute(
            "SELECT file_path, content_hash FROM notes WHERE instance_id = ?",
            (instance_id,),
        )
        return {r["file_path"]: r["content_hash"] for r in rows}

    def _scan_md_files(self, vault_path: str) -> dict[str, Path]:
        """Scan all .md files in the vault, return relative_path -> absolute_path."""
        vault = Path(vault_path)
        result = {}
        for md_file in vault.rglob("*.md"):
            # Skip .obsidian directory
            if ".obsidian" in md_file.parts:
                continue
            rel = md_file.relative_to(vault)
            result[str(rel).replace("\\", "/")] = md_file
        return result

    def _index_file_relations(self, instance_id: str, file_path: str, content: str, vault_path: str) -> None:
        """Extract and index relations for a single file."""
        try:
            frontmatter, body = parse_frontmatter(content)
            relations = extract_all_relations(body, frontmatter, file_path, vault_path, self.storage)
            if relations:
                self.indexer.index_relations(instance_id, relations)
        except Exception as e:
            logger.warning("Failed to extract relations for %s: %s", file_path, e)
