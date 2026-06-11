"""Instance-scoped ontology CRUD service."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from collections.abc import Iterable
from typing import Any

from app.core.ontology_cache import invalidate_ontology_cache
from app.storage.database import DatabaseBackend


class OntologyValidationError(ValueError):
    """Raised when ontology input is invalid."""


class OntologyNotFoundError(ValueError):
    """Raised when an ontology record is not found."""


class OntologyDuplicateError(ValueError):
    """Raised when a unique constraint is violated."""


VALID_RELATION_TYPES = {
    "is_a", "has_role", "part_of", "related_to", "caused_by", "influenced_by",
}
VALID_ENTITY_STATUSES = {"active", "candidate", "deprecated"}
VALID_LINK_TYPES = {"mention", "definition", "source"}
VALID_EVIDENCE_TYPES = {"mention", "quote", "inference"}


class OntologyService:
    """CRUD service for instance-level ontology entities, types, relations, etc."""

    def __init__(self, db: DatabaseBackend, on_change=None):
        self.db = db
        self._on_change = on_change

    def _invalidate(self, instance_id: str) -> None:
        invalidate_ontology_cache(instance_id)
        if self._on_change:
            self._on_change(instance_id)

    # =========================================================================
    # Types
    # =========================================================================

    def list_types(
        self,
        instance_id: str,
        *,
        searchable_only: bool = False,
        status: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_instance(instance_id)
        sql = """SELECT id, instance_id, name, description, parent_type_id,
                        status, searchable, source, confidence, created_at, updated_at
                 FROM ontology_types WHERE instance_id = ?"""
        params: list[Any] = [instance_id]
        if searchable_only:
            sql += " AND searchable = 1 AND status = 'active'"
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        if source is not None:
            sql += " AND source = ?"
            params.append(source)
        sql += " ORDER BY name"
        return [_row_to_type(row) for row in self.db.execute(sql, params)]

    def get_type(self, instance_id: str, type_id: str) -> dict[str, Any]:
        self._ensure_instance(instance_id)
        rows = self.db.execute(
            """SELECT id, instance_id, name, description, parent_type_id,
                      status, searchable, source, confidence, created_at, updated_at
               FROM ontology_types WHERE instance_id = ? AND id = ?""",
            (instance_id, type_id),
        )
        if not rows:
            raise OntologyNotFoundError("Ontology type not found")
        return _row_to_type(rows[0])

    def create_type(
        self,
        instance_id: str,
        *,
        name: str,
        description: str = "",
        parent_type_id: str | None = None,
        source: str = "manual",
        confidence: float = 1.0,
        status: str = "active",
    ) -> dict[str, Any]:
        self._ensure_instance(instance_id)
        if status not in VALID_ENTITY_STATUSES:
            raise OntologyValidationError(f"Invalid status: {status}")
        name = _normalize_name(name, "name")
        name_norm = _norm_key(name)
        self._check_type_unique(instance_id, name_norm, exclude_id=None)

        if parent_type_id is not None:
            self.get_type(instance_id, parent_type_id)

        now = datetime.now(UTC).isoformat()
        type_id = f"type_{uuid.uuid4().hex[:12]}"
        searchable = 0 if status == "candidate" else 1
        self.db.execute(
            """INSERT INTO ontology_types
               (id, instance_id, name, name_norm, description, parent_type_id,
                status, searchable, source, confidence, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (type_id, instance_id, name, name_norm, description, parent_type_id,
             status, searchable, source, _clamp_confidence(confidence), now, now),
        )
        self._invalidate(instance_id)
        return self.get_type(instance_id, type_id)

    def update_type(
        self, instance_id: str, type_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        current = self.get_type(instance_id, type_id)
        name = _normalize_name(updates.get("name", current["name"]), "name")
        name_norm = _norm_key(name)
        if name_norm != _norm_key(current["name"]):
            self._check_type_unique(instance_id, name_norm, exclude_id=type_id)

        new_status = updates.get("status", current["status"])
        if new_status not in VALID_ENTITY_STATUSES:
            raise OntologyValidationError(f"Invalid status: {new_status}")
        # Status drives searchable: candidate -> 0, others -> 1
        if "status" in updates:
            searchable = 0 if new_status == "candidate" else 1
        elif "searchable" in updates:
            # Prevent manually enabling searchable for candidate records
            if current["status"] == "candidate" and updates["searchable"]:
                raise OntologyValidationError("Cannot set searchable=True for candidate status")
            searchable = 1 if updates["searchable"] else 0
        else:
            searchable = current["searchable"]

        now = datetime.now(UTC).isoformat()
        self.db.execute(
            """UPDATE ontology_types
               SET name = ?, name_norm = ?, description = ?, parent_type_id = ?,
                   status = ?, searchable = ?, confidence = ?, updated_at = ?
               WHERE instance_id = ? AND id = ?""",
            (
                name,
                name_norm,
                updates.get("description", current["description"]),
                updates.get("parent_type_id", current["parent_type_id"]),
                new_status,
                searchable,
                _clamp_confidence(updates.get("confidence", current["confidence"])),
                now,
                instance_id,
                type_id,
            ),
        )
        self._invalidate(instance_id)
        return self.get_type(instance_id, type_id)

    def delete_type(self, instance_id: str, type_id: str) -> None:
        self._ensure_instance(instance_id)
        rows = self.db.execute(
            "SELECT id FROM ontology_types WHERE instance_id = ? AND id = ?",
            (instance_id, type_id),
        )
        if not rows:
            raise OntologyNotFoundError("Ontology type not found")
        self.db.execute(
            "DELETE FROM ontology_types WHERE instance_id = ? AND id = ?",
            (instance_id, type_id),
        )
        self._invalidate(instance_id)

    # =========================================================================
    # Entities
    # =========================================================================

    def list_entities(
        self,
        instance_id: str,
        *,
        type_id: str | None = None,
        searchable_only: bool = False,
        status: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_instance(instance_id)
        sql = """SELECT id, instance_id, name, entity_type_id, description,
                        status, searchable, source, confidence, metadata_json,
                        created_at, updated_at
                 FROM ontology_entities WHERE instance_id = ?"""
        params: list[Any] = [instance_id]
        if type_id is not None:
            sql += " AND entity_type_id = ?"
            params.append(type_id)
        if searchable_only:
            sql += " AND searchable = 1 AND status = 'active'"
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        if source is not None:
            sql += " AND source = ?"
            params.append(source)
        sql += " ORDER BY name"
        return [_row_to_entity(row) for row in self.db.execute(sql, params)]

    def get_entity(self, instance_id: str, entity_id: str) -> dict[str, Any]:
        self._ensure_instance(instance_id)
        rows = self.db.execute(
            """SELECT id, instance_id, name, entity_type_id, description,
                      status, searchable, source, confidence, metadata_json,
                      created_at, updated_at
               FROM ontology_entities WHERE instance_id = ? AND id = ?""",
            (instance_id, entity_id),
        )
        if not rows:
            raise OntologyNotFoundError("Ontology entity not found")
        return _row_to_entity(rows[0])

    def create_entity(
        self,
        instance_id: str,
        *,
        name: str,
        entity_type_id: str | None = None,
        description: str = "",
        source: str = "manual",
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        self._ensure_instance(instance_id)
        if status not in VALID_ENTITY_STATUSES:
            raise OntologyValidationError(f"Invalid status: {status}")
        name = _normalize_name(name, "name")
        name_norm = _norm_key(name)
        self._check_entity_unique(instance_id, name_norm, exclude_id=None)

        if entity_type_id is not None:
            self.get_type(instance_id, entity_type_id)

        now = datetime.now(UTC).isoformat()
        entity_id = f"ent_{uuid.uuid4().hex[:12]}"
        searchable = 0 if status == "candidate" else 1
        self.db.execute(
            """INSERT INTO ontology_entities
               (id, instance_id, name, name_norm, entity_type_id, description,
                status, searchable, source, confidence, metadata_json,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entity_id, instance_id, name, name_norm, entity_type_id, description,
                status, searchable, source, _clamp_confidence(confidence),
                json.dumps(metadata or {}, ensure_ascii=False),
                now, now,
            ),
        )
        self._invalidate(instance_id)
        entity = self.get_entity(instance_id, entity_id)
        self.auto_bridge_entity(instance_id, entity_id)
        return entity

    def update_entity(
        self, instance_id: str, entity_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        current = self.get_entity(instance_id, entity_id)
        name = _normalize_name(updates.get("name", current["name"]), "name")
        name_norm = _norm_key(name)
        if name_norm != _norm_key(current["name"]):
            self._check_entity_unique(instance_id, name_norm, exclude_id=entity_id)

        new_status = updates.get("status", current["status"])
        if new_status not in VALID_ENTITY_STATUSES:
            raise OntologyValidationError(f"Invalid status: {new_status}")
        if "status" in updates:
            searchable = 0 if new_status == "candidate" else 1
        elif "searchable" in updates:
            if current["status"] == "candidate" and updates["searchable"]:
                raise OntologyValidationError("Cannot set searchable=True for candidate status")
            searchable = 1 if updates["searchable"] else 0
        else:
            searchable = current["searchable"]

        metadata = updates.get("metadata", current["metadata"])
        if isinstance(metadata, dict):
            metadata = json.dumps(metadata, ensure_ascii=False)

        now = datetime.now(UTC).isoformat()
        self.db.execute(
            """UPDATE ontology_entities
               SET name = ?, name_norm = ?, entity_type_id = ?, description = ?,
                   status = ?, searchable = ?, confidence = ?, metadata_json = ?,
                   updated_at = ?
               WHERE instance_id = ? AND id = ?""",
            (
                name, name_norm,
                updates.get("entity_type_id", current["entity_type_id"]),
                updates.get("description", current["description"]),
                new_status,
                searchable,
                _clamp_confidence(updates.get("confidence", current["confidence"])),
                metadata,
                now, instance_id, entity_id,
            ),
        )
        self._invalidate(instance_id)
        entity = self.get_entity(instance_id, entity_id)
        self.auto_bridge_entity(instance_id, entity_id)
        return entity

    def delete_entity(self, instance_id: str, entity_id: str) -> None:
        self._ensure_instance(instance_id)
        rows = self.db.execute(
            "SELECT id FROM ontology_entities WHERE instance_id = ? AND id = ?",
            (instance_id, entity_id),
        )
        if not rows:
            raise OntologyNotFoundError("Ontology entity not found")
        self.db.execute(
            "DELETE FROM ontology_entities WHERE instance_id = ? AND id = ?",
            (instance_id, entity_id),
        )
        self._invalidate(instance_id)

    # =========================================================================
    # Aliases
    # =========================================================================

    def list_aliases(self, instance_id: str, entity_id: str) -> list[dict[str, Any]]:
        self._ensure_instance(instance_id)
        self.get_entity(instance_id, entity_id)
        rows = self.db.execute(
            """SELECT id, instance_id, entity_id, alias_text, source, created_at
               FROM ontology_entity_aliases
               WHERE instance_id = ? AND entity_id = ?
               ORDER BY alias_text""",
            (instance_id, entity_id),
        )
        return [_row_to_alias(row) for row in rows]

    def add_alias(
        self,
        instance_id: str,
        entity_id: str,
        alias_text: str,
        source: str = "manual",
    ) -> dict[str, Any]:
        self._ensure_instance(instance_id)
        self.get_entity(instance_id, entity_id)
        alias_text = _normalize_name(alias_text, "alias_text")
        alias_norm = _norm_key(alias_text)

        rows = self.db.execute(
            """SELECT id FROM ontology_entity_aliases
               WHERE instance_id = ? AND entity_id = ? AND alias_norm = ?""",
            (instance_id, entity_id, alias_norm),
        )
        if rows:
            raise OntologyDuplicateError("Alias already exists for this entity")

        now = datetime.now(UTC).isoformat()
        alias_id = f"alias_{uuid.uuid4().hex[:12]}"
        self.db.execute(
            """INSERT INTO ontology_entity_aliases
               (id, instance_id, entity_id, alias_text, alias_norm, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (alias_id, instance_id, entity_id, alias_text, alias_norm, source, now),
        )
        self._invalidate(instance_id)
        rows = self.db.execute(
            """SELECT id, instance_id, entity_id, alias_text, source, created_at
               FROM ontology_entity_aliases WHERE id = ?""",
            (alias_id,),
        )
        self.auto_bridge_entity(instance_id, entity_id, extra_terms=[alias_text])
        return _row_to_alias(rows[0])

    def delete_alias(self, instance_id: str, alias_id: str) -> None:
        self._ensure_instance(instance_id)
        rows = self.db.execute(
            "SELECT id FROM ontology_entity_aliases WHERE instance_id = ? AND id = ?",
            (instance_id, alias_id),
        )
        if not rows:
            raise OntologyNotFoundError("Alias not found")
        self.db.execute(
            "DELETE FROM ontology_entity_aliases WHERE instance_id = ? AND id = ?",
            (instance_id, alias_id),
        )
        self._invalidate(instance_id)

    # =========================================================================
    # Relations
    # =========================================================================

    def list_relations(
        self,
        instance_id: str,
        *,
        entity_id: str | None = None,
        relation_type: str | None = None,
        searchable_only: bool = False,
        status: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_instance(instance_id)
        sql = """SELECT id, instance_id, source_entity_id, target_entity_id,
                        relation_type, description, status, searchable, source,
                        confidence, created_at, updated_at
                 FROM ontology_relations WHERE instance_id = ?"""
        params: list[Any] = [instance_id]
        if entity_id is not None:
            sql += " AND (source_entity_id = ? OR target_entity_id = ?)"
            params.extend([entity_id, entity_id])
        if relation_type is not None:
            sql += " AND relation_type = ?"
            params.append(relation_type)
        if searchable_only:
            sql += " AND searchable = 1 AND status = 'active'"
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        if source is not None:
            sql += " AND source = ?"
            params.append(source)
        sql += " ORDER BY created_at DESC"
        relations = [_row_to_relation(row) for row in self.db.execute(sql, params)]
        return self._with_relation_entities_batch(relations)

    def get_relation(self, instance_id: str, relation_id: str) -> dict[str, Any]:
        self._ensure_instance(instance_id)
        rows = self.db.execute(
            """SELECT id, instance_id, source_entity_id, target_entity_id,
                      relation_type, description, status, searchable, source,
                      confidence, created_at, updated_at
               FROM ontology_relations WHERE instance_id = ? AND id = ?""",
            (instance_id, relation_id),
        )
        if not rows:
            raise OntologyNotFoundError("Ontology relation not found")
        return self._with_relation_entities(_row_to_relation(rows[0]))

    def create_relation(
        self,
        instance_id: str,
        *,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
        description: str = "",
        source: str = "manual",
        confidence: float = 1.0,
        status: str = "active",
    ) -> dict[str, Any]:
        self._ensure_instance(instance_id)
        if status not in VALID_ENTITY_STATUSES:
            raise OntologyValidationError(f"Invalid status: {status}")
        self.get_entity(instance_id, source_entity_id)
        self.get_entity(instance_id, target_entity_id)
        relation_type = _validate_relation_type(relation_type)

        rows = self.db.execute(
            """SELECT id FROM ontology_relations
               WHERE instance_id = ? AND source_entity_id = ? AND target_entity_id = ? AND relation_type = ?""",
            (instance_id, source_entity_id, target_entity_id, relation_type),
        )
        if rows:
            raise OntologyDuplicateError("Relation already exists")

        now = datetime.now(UTC).isoformat()
        rel_id = f"rel_{uuid.uuid4().hex[:12]}"
        searchable = 0 if status == "candidate" else 1
        self.db.execute(
            """INSERT INTO ontology_relations
               (id, instance_id, source_entity_id, target_entity_id, relation_type,
                description, status, searchable, source, confidence, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rel_id, instance_id, source_entity_id, target_entity_id, relation_type,
             description, status, searchable, source, _clamp_confidence(confidence), now, now),
        )
        self._invalidate(instance_id)
        return self.get_relation(instance_id, rel_id)

    def update_relation(
        self, instance_id: str, relation_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        current = self.get_relation(instance_id, relation_id)

        new_status = updates.get("status", current["status"])
        if new_status not in VALID_ENTITY_STATUSES:
            raise OntologyValidationError(f"Invalid status: {new_status}")
        if "status" in updates:
            searchable = 0 if new_status == "candidate" else 1
        elif "searchable" in updates:
            if current["status"] == "candidate" and updates["searchable"]:
                raise OntologyValidationError("Cannot set searchable=True for candidate status")
            searchable = 1 if updates["searchable"] else 0
        else:
            searchable = current["searchable"]

        now = datetime.now(UTC).isoformat()
        self.db.execute(
            """UPDATE ontology_relations
               SET description = ?, status = ?, searchable = ?, confidence = ?, updated_at = ?
               WHERE instance_id = ? AND id = ?""",
            (
                updates.get("description", current["description"]),
                new_status,
                searchable,
                _clamp_confidence(updates.get("confidence", current["confidence"])),
                now, instance_id, relation_id,
            ),
        )
        self._invalidate(instance_id)
        return self.get_relation(instance_id, relation_id)

    def delete_relation(self, instance_id: str, relation_id: str) -> None:
        self._ensure_instance(instance_id)
        rows = self.db.execute(
            "SELECT id FROM ontology_relations WHERE instance_id = ? AND id = ?",
            (instance_id, relation_id),
        )
        if not rows:
            raise OntologyNotFoundError("Ontology relation not found")
        self.db.execute(
            "DELETE FROM ontology_relations WHERE instance_id = ? AND id = ?",
            (instance_id, relation_id),
        )
        self._invalidate(instance_id)

    # =========================================================================
    # Batch operations
    # =========================================================================

    def batch_update_status(
        self,
        instance_id: str,
        entity_type: str,
        ids: list[str],
        status: str,
    ) -> dict[str, Any]:
        """Batch update status for types, entities, or relations.

        Returns {"updated": int, "not_found": list[str]}.
        """
        self._ensure_instance(instance_id)
        if status not in VALID_ENTITY_STATUSES:
            raise OntologyValidationError(f"Invalid status: {status}")
        if entity_type not in ("type", "entity", "relation"):
            raise OntologyValidationError(f"Invalid entity_type: {entity_type}")

        table = {
            "type": "ontology_types",
            "entity": "ontology_entities",
            "relation": "ontology_relations",
        }[entity_type]

        now = datetime.now(UTC).isoformat()
        updated = 0
        not_found: list[str] = []

        for item_id in ids:
            rows = self.db.execute(
                f"SELECT id FROM {table} WHERE instance_id = ? AND id = ?",
                (instance_id, item_id),
            )
            if not rows:
                not_found.append(item_id)
                continue
            searchable = 0 if status == "candidate" else 1
            self.db.execute(
                f"UPDATE {table} SET status = ?, searchable = ?, updated_at = ? WHERE instance_id = ? AND id = ?",
                (status, searchable, now, instance_id, item_id),
            )
            updated += 1

        if updated > 0:
            self._invalidate(instance_id)
        return {"updated": updated, "not_found": not_found}

    # =========================================================================
    # Evidence
    # =========================================================================

    def list_evidence(self, instance_id: str, relation_id: str) -> list[dict[str, Any]]:
        self._ensure_instance(instance_id)
        self.get_relation(instance_id, relation_id)
        rows = self.db.execute(
            """SELECT id, instance_id, relation_id, file_path, evidence_type,
                      snippet, confidence, status, created_at
               FROM ontology_relation_evidence
               WHERE instance_id = ? AND relation_id = ?
               ORDER BY created_at DESC""",
            (instance_id, relation_id),
        )
        return [_row_to_evidence(row) for row in rows]

    def add_evidence(
        self,
        instance_id: str,
        relation_id: str,
        file_path: str,
        evidence_type: str = "mention",
        snippet: str = "",
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        self._ensure_instance(instance_id)
        self.get_relation(instance_id, relation_id)
        evidence_type = _validate_evidence_type(evidence_type)

        now = datetime.now(UTC).isoformat()
        evid_id = f"evid_{uuid.uuid4().hex[:12]}"
        self.db.execute(
            """INSERT INTO ontology_relation_evidence
               (id, instance_id, relation_id, file_path, evidence_type,
                snippet, confidence, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
            (evid_id, instance_id, relation_id, file_path, evidence_type,
             snippet, _clamp_confidence(confidence), now),
        )
        rows = self.db.execute(
            """SELECT id, instance_id, relation_id, file_path, evidence_type,
                      snippet, confidence, status, created_at
               FROM ontology_relation_evidence WHERE id = ?""",
            (evid_id,),
        )
        return _row_to_evidence(rows[0])

    # =========================================================================
    # Entity-Note Links
    # =========================================================================

    def list_entity_links(self, instance_id: str, entity_id: str) -> list[dict[str, Any]]:
        self._ensure_instance(instance_id)
        self.get_entity(instance_id, entity_id)
        rows = self.db.execute(
            """SELECT id, instance_id, entity_id, file_path, link_type,
                      snippet, confidence, status, created_at
               FROM ontology_entity_note_links
               WHERE instance_id = ? AND entity_id = ?
               ORDER BY created_at DESC""",
            (instance_id, entity_id),
        )
        return [_row_to_link(row) for row in rows]

    def add_entity_link(
        self,
        instance_id: str,
        entity_id: str,
        file_path: str,
        link_type: str = "mention",
        snippet: str = "",
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        self._ensure_instance(instance_id)
        self.get_entity(instance_id, entity_id)
        link_type = _validate_link_type(link_type)

        rows = self.db.execute(
            """SELECT id FROM ontology_entity_note_links
               WHERE instance_id = ? AND entity_id = ? AND file_path = ? AND link_type = ?""",
            (instance_id, entity_id, file_path, link_type),
        )
        if rows:
            raise OntologyDuplicateError("Entity-note link already exists")

        now = datetime.now(UTC).isoformat()
        link_id = f"link_{uuid.uuid4().hex[:12]}"
        self.db.execute(
            """INSERT INTO ontology_entity_note_links
               (id, instance_id, entity_id, file_path, link_type,
                snippet, confidence, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
            (link_id, instance_id, entity_id, file_path, link_type,
             snippet, _clamp_confidence(confidence), now),
        )
        rows = self.db.execute(
            """SELECT id, instance_id, entity_id, file_path, link_type,
                      snippet, confidence, status, created_at
               FROM ontology_entity_note_links WHERE id = ?""",
            (link_id,),
        )
        return _row_to_link(rows[0])

    def auto_bridge_entity(
        self,
        instance_id: str,
        entity_id: str,
        *,
        extra_terms: list[str] | None = None,
    ) -> dict[str, int]:
        """Create note links for an entity by matching note titles and facets."""
        entity = self.get_entity(instance_id, entity_id)
        terms = [entity["name"], *[item["alias_text"] for item in self.list_aliases(instance_id, entity_id)]]
        if extra_terms:
            terms.extend(extra_terms)

        unique_terms = _dedupe_terms(terms)
        created = 0
        skipped = 0
        linked_paths: set[str] = set()

        for term in unique_terms:
            rows = self.db.execute(
                "SELECT file_path, title FROM notes WHERE instance_id = ? AND title LIKE ?",
                (instance_id, f"%{term}%"),
            )
            for row in rows:
                path = row["file_path"]
                if path in linked_paths:
                    skipped += 1
                    continue
                title = str(row["title"] or "").strip()
                exact = title == term
                created += self._add_entity_link_if_missing(
                    instance_id,
                    entity_id,
                    path,
                    link_type="definition" if exact else "mention",
                    snippet=f"Auto-linked from {term}",
                    confidence=0.8 if exact else 0.5,
                )
                linked_paths.add(path)

        if unique_terms:
            placeholders = ",".join("?" * len(unique_terms))
            rows = self.db.execute(
                f"""SELECT DISTINCT file_path
                    FROM note_facets
                    WHERE instance_id = ?
                      AND field IN ('concepts', 'aliases')
                      AND value IN ({placeholders})""",
                [instance_id, *unique_terms],
            )
            for row in rows:
                path = row["file_path"]
                if path in linked_paths:
                    skipped += 1
                    continue
                created += self._add_entity_link_if_missing(
                    instance_id,
                    entity_id,
                    path,
                    link_type="mention",
                    snippet=f"Auto-linked from facet match",
                    confidence=0.7,
                )
                linked_paths.add(path)

        return {"created": created, "skipped": skipped}

    def backfill_entity_links(self, instance_id: str) -> dict[str, int]:
        """Backfill note links for all active searchable ontology entities."""
        self._ensure_instance(instance_id)
        entities = self.list_entities(instance_id, searchable_only=True, status="active")
        created = 0
        skipped = 0
        for entity in entities:
            result = self.auto_bridge_entity(instance_id, entity["id"])
            created += result["created"]
            skipped += result["skipped"]
        return {"entities": len(entities), "created": created, "skipped": skipped}

    def _add_entity_link_if_missing(
        self,
        instance_id: str,
        entity_id: str,
        file_path: str,
        *,
        link_type: str,
        snippet: str,
        confidence: float,
    ) -> int:
        try:
            self.add_entity_link(
                instance_id,
                entity_id,
                file_path,
                link_type=link_type,
                snippet=snippet,
                confidence=confidence,
            )
            return 1
        except OntologyDuplicateError:
            return 0

    # =========================================================================
    # Type Hierarchy
    # =========================================================================

    def get_type_children(self, instance_id: str, type_id: str) -> list[dict[str, Any]]:
        self._ensure_instance(instance_id)
        self.get_type(instance_id, type_id)
        rows = self.db.execute(
            """SELECT t.id, t.instance_id, t.name, t.description, t.parent_type_id,
                      t.status, t.searchable, t.source, t.confidence, t.created_at, t.updated_at
               FROM ontology_types t
               JOIN ontology_type_hierarchy h ON t.id = h.child_type_id
               WHERE h.instance_id = ? AND h.parent_type_id = ?
               ORDER BY t.name""",
            (instance_id, type_id),
        )
        return [_row_to_type(row) for row in rows]

    def get_type_ancestors(self, instance_id: str, type_id: str) -> list[dict[str, Any]]:
        self._ensure_instance(instance_id)
        self.get_type(instance_id, type_id)
        rows = self.db.execute(
            """WITH RECURSIVE ancestors AS (
                   SELECT parent_type_id, depth
                   FROM ontology_type_hierarchy
                   WHERE instance_id = ? AND child_type_id = ?
                   UNION ALL
                   SELECT h.parent_type_id, h.depth
                   FROM ontology_type_hierarchy h
                   JOIN ancestors a ON h.child_type_id = a.parent_type_id
                   WHERE h.instance_id = ?
               )
               SELECT t.id, t.instance_id, t.name, t.description, t.parent_type_id,
                      t.status, t.searchable, t.source, t.confidence, t.created_at, t.updated_at
               FROM ontology_types t
               JOIN ancestors a ON t.id = a.parent_type_id
               ORDER BY a.depth""",
            (instance_id, type_id, instance_id),
        )
        return [_row_to_type(row) for row in rows]

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _ensure_instance(self, instance_id: str) -> None:
        rows = self.db.execute("SELECT id FROM instances WHERE id = ?", (instance_id,))
        if not rows:
            raise OntologyNotFoundError(f"Instance {instance_id} not found")

    def _with_relation_entities(self, relation: dict[str, Any]) -> dict[str, Any]:
        entities = self._batch_get_entities(
            relation["instance_id"],
            [relation["source_entity_id"], relation["target_entity_id"]],
        )
        relation["source_entity"] = entities.get(relation["source_entity_id"])
        relation["target_entity"] = entities.get(relation["target_entity_id"])
        return relation

    def _with_relation_entities_batch(self, relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not relations:
            return []
        by_instance: dict[str, set[str]] = {}
        for relation in relations:
            by_instance.setdefault(relation["instance_id"], set()).update(
                [relation["source_entity_id"], relation["target_entity_id"]]
            )
        entities_by_instance = {
            instance_id: self._batch_get_entities(instance_id, entity_ids)
            for instance_id, entity_ids in by_instance.items()
        }
        for relation in relations:
            entities = entities_by_instance.get(relation["instance_id"], {})
            relation["source_entity"] = entities.get(relation["source_entity_id"])
            relation["target_entity"] = entities.get(relation["target_entity_id"])
        return relations

    def _batch_get_entities(self, instance_id: str, entity_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        ids = sorted({entity_id for entity_id in entity_ids if entity_id})
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        rows = self.db.execute(
            f"""SELECT id, instance_id, name, entity_type_id, description,
                       status, searchable, source, confidence, metadata_json,
                       created_at, updated_at
                FROM ontology_entities
                WHERE instance_id = ? AND id IN ({placeholders})""",
            [instance_id, *ids],
        )
        return {row["id"]: _row_to_entity(row) for row in rows}

    def _check_type_unique(self, instance_id: str, name_norm: str, *, exclude_id: str | None) -> None:
        sql = "SELECT id FROM ontology_types WHERE instance_id = ? AND name_norm = ?"
        params: list[Any] = [instance_id, name_norm]
        if exclude_id:
            sql += " AND id != ?"
            params.append(exclude_id)
        if self.db.execute(sql, params):
            raise OntologyDuplicateError("Ontology type with this name already exists")

    def _check_entity_unique(self, instance_id: str, name_norm: str, *, exclude_id: str | None) -> None:
        sql = "SELECT id FROM ontology_entities WHERE instance_id = ? AND name_norm = ?"
        params: list[Any] = [instance_id, name_norm]
        if exclude_id:
            sql += " AND id != ?"
            params.append(exclude_id)
        if self.db.execute(sql, params):
            raise OntologyDuplicateError("Ontology entity with this name already exists")


# =============================================================================
# Row converters
# =============================================================================

def _row_to_type(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "instance_id": row["instance_id"],
        "name": row["name"],
        "description": row.get("description") or "",
        "parent_type_id": row.get("parent_type_id"),
        "status": row["status"],
        "searchable": bool(row.get("searchable", 1)),
        "source": row.get("source") or "manual",
        "confidence": float(row.get("confidence", 1.0)),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_entity(row: dict[str, Any]) -> dict[str, Any]:
    metadata = {}
    raw = row.get("metadata_json")
    if raw:
        try:
            metadata = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            metadata = {}
    return {
        "id": row["id"],
        "instance_id": row["instance_id"],
        "name": row["name"],
        "entity_type_id": row.get("entity_type_id"),
        "description": row.get("description") or "",
        "status": row["status"],
        "searchable": bool(row.get("searchable", 1)),
        "source": row.get("source") or "manual",
        "confidence": float(row.get("confidence", 1.0)),
        "metadata": metadata,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_alias(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "instance_id": row["instance_id"],
        "entity_id": row["entity_id"],
        "alias_text": row["alias_text"],
        "source": row.get("source") or "manual",
        "created_at": row["created_at"],
    }


def _row_to_relation(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "instance_id": row["instance_id"],
        "source_entity_id": row["source_entity_id"],
        "target_entity_id": row["target_entity_id"],
        "relation_type": row["relation_type"],
        "description": row.get("description") or "",
        "status": row["status"],
        "searchable": bool(row.get("searchable", 1)),
        "source": row.get("source") or "manual",
        "confidence": float(row.get("confidence", 1.0)),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_evidence(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "instance_id": row["instance_id"],
        "relation_id": row["relation_id"],
        "file_path": row["file_path"],
        "evidence_type": row["evidence_type"],
        "snippet": row.get("snippet") or "",
        "confidence": float(row.get("confidence", 1.0)),
        "status": row["status"],
        "created_at": row["created_at"],
    }


def _row_to_link(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "instance_id": row["instance_id"],
        "entity_id": row["entity_id"],
        "file_path": row["file_path"],
        "link_type": row["link_type"],
        "snippet": row.get("snippet") or "",
        "confidence": float(row.get("confidence", 1.0)),
        "status": row["status"],
        "created_at": row["created_at"],
    }


# =============================================================================
# Normalization & validation
# =============================================================================

def _normalize_name(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise OntologyValidationError(f"{field} is required")
    return text


def _dedupe_terms(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = _norm_key(text)
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _norm_key(value: str) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _clamp_confidence(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, v))


def _validate_relation_type(value: str) -> str:
    text = str(value or "").strip().lower()
    if text not in VALID_RELATION_TYPES:
        raise OntologyValidationError(f"relation_type must be one of {VALID_RELATION_TYPES}")
    return text


def _validate_link_type(value: str) -> str:
    text = str(value or "").strip().lower()
    if text not in VALID_LINK_TYPES:
        raise OntologyValidationError(f"link_type must be one of {VALID_LINK_TYPES}")
    return text


def _validate_evidence_type(value: str) -> str:
    text = str(value or "").strip().lower()
    if text not in VALID_EVIDENCE_TYPES:
        raise OntologyValidationError(f"evidence_type must be one of {VALID_EVIDENCE_TYPES}")
    return text
