"""Instance service - manages knowledge base instances."""

import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.exceptions import InstanceAlreadyExistsError, InstanceNotFoundError
from app.storage.database import DatabaseBackend
from app.storage.filesystem import StorageBackend
from app.template.registry import TemplateRegistry
from app.template.scaffolding import create_instance_scaffold

logger = logging.getLogger(__name__)

SUPPORTED_INSTANCE_LANGUAGES = {"zh", "en"}
DEFAULT_INSTANCE_LANGUAGE = "zh"


class InstanceInfo:
    """Instance information returned to callers."""

    def __init__(self, data: dict[str, Any]):
        self.id: str = data["id"]
        self.name: str = data["name"]
        self.template_id: str = data["template_id"]
        self.vault_path: str = data["vault_path"]
        self.auto_map: bool = bool(data.get("auto_map", True))
        self.language: str = _normalize_instance_language(data.get("language"))
        self.created_at: str = data["created_at"]
        self.updated_at: str = data["updated_at"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "template_id": self.template_id,
            "vault_path": self.vault_path,
            "auto_map": self.auto_map,
            "language": self.language,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class InstanceService:
    """Manages knowledge base instances.

    Reference: 详细设计文档 Section 4
    """

    def __init__(
        self,
        db: DatabaseBackend,
        storage: StorageBackend,
        template_registry: TemplateRegistry,
        settings: Settings,
    ):
        self.db = db
        self.storage = storage
        self.template_registry = template_registry
        self.settings = settings

    def create_instance(
        self,
        name: str,
        template_id: str = "standard_v1",
        auto_map: bool = True,
        language: str = DEFAULT_INSTANCE_LANGUAGE,
        config: dict | None = None,
    ) -> InstanceInfo:
        """Create a new knowledge base instance.

        1. Validate template exists
        2. Generate instance ID
        3. Create vault directory structure
        4. Write instance.yaml
        5. Initialize SQLite tables
        6. Return instance info
        """
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Instance name is required")

        existing = self.db.execute(
            "SELECT id FROM instances WHERE lower(trim(name)) = lower(?) LIMIT 1",
            (normalized_name,),
        )
        if existing:
            raise InstanceAlreadyExistsError(normalized_name)

        # Validate template
        template_def = self.template_registry.get_template(template_id)

        # Generate ID and paths. Instance names are display labels only; using
        # them as directories would make path traversal possible.
        instance_id = f"inst_{uuid.uuid4().hex[:12]}"
        data_dir = Path(self.settings.data_dir).resolve()
        vault_dir = (data_dir / instance_id).resolve()
        if not vault_dir.is_relative_to(data_dir) or vault_dir == data_dir:
            raise ValueError("Instance vault path is outside the configured data directory")
        vault_path = str(vault_dir)

        now = datetime.now(timezone.utc).isoformat()
        instance_config = dict(config or {})
        instance_config["language"] = _normalize_instance_language(language)

        # Create vault directory scaffold
        create_instance_scaffold(
            vault_path=vault_path,
            instance_id=instance_id,
            instance_name=normalized_name,
            template_id=template_id,
            auto_map=auto_map,
            directory_skeleton=template_def.directory_skeleton,
        )

        # Insert into database
        self.db.execute(
            """INSERT INTO instances (id, name, template_id, vault_path, auto_map, config_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                instance_id,
                normalized_name,
                template_id,
                vault_path,
                int(auto_map),
                json.dumps(instance_config, ensure_ascii=False),
                now,
                now,
            ),
        )

        logger.info(f"Created instance: {instance_id} ({normalized_name}) at {vault_path}")

        return InstanceInfo({
            "id": instance_id,
            "name": normalized_name,
            "template_id": template_id,
            "vault_path": vault_path,
            "auto_map": auto_map,
            "language": instance_config["language"],
            "created_at": now,
            "updated_at": now,
        })

    def list_instances(self) -> list[InstanceInfo]:
        """List all knowledge base instances."""
        rows = self.db.execute(
            "SELECT id, name, template_id, vault_path, auto_map, config_json, created_at, updated_at FROM instances ORDER BY created_at"
        )
        return [InstanceInfo(_row_with_language(row)) for row in rows]

    def get_instance(self, instance_id: str) -> InstanceInfo:
        """Get a single instance by ID."""
        rows = self.db.execute(
            "SELECT id, name, template_id, vault_path, auto_map, config_json, created_at, updated_at FROM instances WHERE id = ?",
            (instance_id,),
        )
        if not rows:
            raise InstanceNotFoundError(instance_id)
        return InstanceInfo(_row_with_language(rows[0]))

    def update_instance(
        self,
        instance_id: str,
        *,
        name: str | None = None,
        auto_map: bool | None = None,
    ) -> InstanceInfo:
        """Update editable instance metadata without moving the vault directory."""
        current = self.get_instance(instance_id)
        next_name = current.name if name is None else name.strip()
        if not next_name:
            raise ValueError("Instance name is required")

        duplicate = self.db.execute(
            """SELECT id FROM instances
               WHERE id != ? AND lower(trim(name)) = lower(?) LIMIT 1""",
            (instance_id, next_name),
        )
        if duplicate:
            raise InstanceAlreadyExistsError(next_name)

        next_auto_map = current.auto_map if auto_map is None else bool(auto_map)
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            """UPDATE instances
               SET name = ?, auto_map = ?, updated_at = ?
               WHERE id = ?""",
            (next_name, int(next_auto_map), now, instance_id),
        )
        return self.get_instance(instance_id)

    def delete_instance(self, instance_id: str, *, delete_files: bool = False) -> bool:
        """Delete an instance record and all indexed data, optionally removing its vault."""
        current = self.get_instance(instance_id)
        vault_path = Path(current.vault_path).resolve()
        data_dir = Path(self.settings.data_dir).resolve()

        if delete_files:
            if not vault_path.is_relative_to(data_dir) or vault_path == data_dir:
                raise ValueError("Instance vault path is outside the configured data directory")

        from app.storage.indexer import Indexer
        from app.pipeline.query_dictionary import invalidate_query_caches

        Indexer(self.db).clear_instance_index(instance_id)
        self.db.execute("DELETE FROM ingest_jobs WHERE instance_id = ?", (instance_id,))
        self.db.execute("DELETE FROM instance_search_lexicon WHERE instance_id = ?", (instance_id,))
        self.db.execute("DELETE FROM instances WHERE id = ?", (instance_id,))
        invalidate_query_caches(instance_id)

        if delete_files and vault_path.exists():
            shutil.rmtree(vault_path)

        return True


def _normalize_instance_language(value: Any) -> str:
    language = str(value or DEFAULT_INSTANCE_LANGUAGE).strip().lower()
    return language if language in SUPPORTED_INSTANCE_LANGUAGES else DEFAULT_INSTANCE_LANGUAGE


def _row_with_language(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    config = _parse_config(data.get("config_json"))
    data["language"] = _normalize_instance_language(config.get("language"))
    return data


def _parse_config(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
