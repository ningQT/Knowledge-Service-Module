"""Sync service — git sync and reindex operations."""

import logging
import subprocess

from app.exceptions import InstanceNotFoundError, SyncFailedError, ReindexFailedError
from app.pipeline.reindex_pipeline import ReindexPipeline, ReindexResult
from app.pipeline.sync_pipeline import SyncPipeline, SyncResult
from app.storage.database import DatabaseBackend
from app.storage.indexer import Indexer
from app.storage.local_backend import LocalStorageBackend

logger = logging.getLogger(__name__)


class SyncService:
    """High-level sync service for git sync and reindex."""

    def __init__(self, db: DatabaseBackend, storage: LocalStorageBackend, indexer: Indexer):
        self.db = db
        self.storage = storage
        self.indexer = indexer

    def sync_from_git(self, instance_id: str, vault_path: str) -> SyncResult:
        """Git pull + sync pipeline.

        1. Run git pull in the vault directory
        2. Run sync pipeline to detect and apply changes
        """
        # Verify instance exists
        instance = self.db.execute(
            "SELECT id FROM instances WHERE id = ?", (instance_id,)
        )
        if not instance:
            raise InstanceNotFoundError(f"Instance {instance_id} not found")

        # Git pull
        try:
            result = subprocess.run(
                ["git", "pull", "--rebase"],
                cwd=vault_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.warning("Git pull returned non-zero: %s", result.stderr)
        except FileNotFoundError:
            logger.info("Git not available, skipping pull")
        except subprocess.TimeoutExpired:
            raise SyncFailedError("Git pull timed out")
        except Exception as e:
            logger.warning("Git pull failed: %s", e)

        # Run sync pipeline
        pipeline = SyncPipeline(self.db, self.storage, self.indexer)
        return pipeline.execute(instance_id, vault_path)

    def sync(self, instance_id: str, vault_path: str) -> SyncResult:
        """Run sync pipeline without git pull."""
        instance = self.db.execute(
            "SELECT id FROM instances WHERE id = ?", (instance_id,)
        )
        if not instance:
            raise InstanceNotFoundError(f"Instance {instance_id} not found")

        pipeline = SyncPipeline(self.db, self.storage, self.indexer)
        return pipeline.execute(instance_id, vault_path)

    def reindex(self, instance_id: str, vault_path: str) -> ReindexResult:
        """Full reindex of an instance."""
        instance = self.db.execute(
            "SELECT id FROM instances WHERE id = ?", (instance_id,)
        )
        if not instance:
            raise InstanceNotFoundError(f"Instance {instance_id} not found")

        pipeline = ReindexPipeline(self.db, self.storage, self.indexer)
        return pipeline.execute(instance_id, vault_path)
