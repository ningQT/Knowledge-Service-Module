"""Instance-scoped ontology cache for fast entity/type/alias lookup."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.storage.database import DatabaseBackend


@dataclass
class OntologyEntityInfo:
    entity_id: str
    name: str
    name_norm: str
    entity_type_id: str | None = None
    status: str = "active"
    searchable: int = 1
    confidence: float = 1.0


@dataclass
class OntologyTypeInfo:
    type_id: str
    name: str
    name_norm: str
    parent_type_id: str | None = None
    status: str = "active"
    searchable: int = 1


@dataclass
class OntologyAliasInfo:
    alias_id: str
    entity_id: str
    alias_text: str
    alias_norm: str


@dataclass
class OntologyCacheData:
    instance_id: str
    entity_names: dict[str, list[OntologyEntityInfo]] = field(default_factory=dict)
    entity_aliases: dict[str, list[OntologyAliasInfo]] = field(default_factory=dict)
    type_names: dict[str, list[OntologyTypeInfo]] = field(default_factory=dict)
    type_to_entities: dict[str, list[str]] = field(default_factory=dict)
    built_at: str | None = None


_cache: dict[str, OntologyCacheData] = {}
_cache_lock = threading.Lock()


def invalidate_ontology_cache(instance_id: str | None = None) -> None:
    """Invalidate ontology cache for a specific instance or all instances."""
    with _cache_lock:
        if instance_id is None:
            _cache.clear()
        else:
            _cache.pop(instance_id, None)


def get_ontology_cache(instance_id: str, db: DatabaseBackend) -> OntologyCacheData:
    """Get cached ontology data, building it if not yet cached."""
    with _cache_lock:
        cached = _cache.get(instance_id)
    if cached is not None:
        return cached

    built = _build_ontology_cache(instance_id, db)
    with _cache_lock:
        _cache[instance_id] = built
    return built


def refresh_ontology_cache(instance_id: str, db: DatabaseBackend) -> OntologyCacheData:
    """Force refresh ontology cache for an instance."""
    built = _build_ontology_cache(instance_id, db)
    with _cache_lock:
        _cache[instance_id] = built
    return built


def _build_ontology_cache(instance_id: str, db: DatabaseBackend) -> OntologyCacheData:
    """Build ontology cache from database."""
    cache = OntologyCacheData(instance_id=instance_id)

    _load_types(cache, db)
    _load_entities(cache, db)
    _load_aliases(cache, db)

    cache.built_at = datetime.now(UTC).isoformat()
    return cache


def _load_types(cache: OntologyCacheData, db: DatabaseBackend) -> None:
    """Load ontology types into cache."""
    rows = db.execute(
        """SELECT id, name, name_norm, parent_type_id, status, searchable
           FROM ontology_types
           WHERE instance_id = ? AND status != 'deprecated'""",
        (cache.instance_id,),
    )
    for row in rows:
        info = OntologyTypeInfo(
            type_id=row["id"],
            name=row["name"],
            name_norm=row["name_norm"],
            parent_type_id=row.get("parent_type_id"),
            status=row["status"],
            searchable=int(row.get("searchable", 1)),
        )
        cache.type_names.setdefault(info.name_norm, []).append(info)


def _load_entities(cache: OntologyCacheData, db: DatabaseBackend) -> None:
    """Load ontology entities into cache."""
    rows = db.execute(
        """SELECT id, name, name_norm, entity_type_id, status, searchable, confidence
           FROM ontology_entities
           WHERE instance_id = ? AND status != 'deprecated'""",
        (cache.instance_id,),
    )
    for row in rows:
        info = OntologyEntityInfo(
            entity_id=row["id"],
            name=row["name"],
            name_norm=row["name_norm"],
            entity_type_id=row.get("entity_type_id"),
            status=row["status"],
            searchable=int(row.get("searchable", 1)),
            confidence=float(row.get("confidence", 1.0)),
        )
        cache.entity_names.setdefault(info.name_norm, []).append(info)

        if info.entity_type_id:
            cache.type_to_entities.setdefault(info.entity_type_id, []).append(info.entity_id)


def _load_aliases(cache: OntologyCacheData, db: DatabaseBackend) -> None:
    """Load entity aliases into cache."""
    rows = db.execute(
        """SELECT a.id, a.entity_id, a.alias_text, a.alias_norm
           FROM ontology_entity_aliases a
           JOIN ontology_entities e ON a.entity_id = e.id
           WHERE a.instance_id = ? AND e.status != 'deprecated'""",
        (cache.instance_id,),
    )
    for row in rows:
        info = OntologyAliasInfo(
            alias_id=row["id"],
            entity_id=row["entity_id"],
            alias_text=row["alias_text"],
            alias_norm=row["alias_norm"],
        )
        cache.entity_aliases.setdefault(info.alias_norm, []).append(info)
