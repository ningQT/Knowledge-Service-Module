"""Note service — read and return structured note content."""

import json
import logging
from pathlib import Path

from app.exceptions import InstanceNotFoundError
from app.pipeline.query_dictionary import invalidate_query_caches
from app.schema.parser import parse_frontmatter, serialize_frontmatter
from app.storage.indexer import Indexer
from app.storage.database import DatabaseBackend
from app.storage.local_backend import LocalStorageBackend
from app.storage.path_utils import (
    normalize_vault_path,
    resolve_vault_relative_path,
    validate_vault_relative_path,
)

logger = logging.getLogger(__name__)


class NoteInfo:
    """Structured note information."""

    def __init__(
        self,
        file_path: str,
        title: str,
        note_type: str,
        domain: str | None,
        kind: str | None,
        graph_layer: int,
        graph_role: str | None,
        verification: str,
        status: str,
        frontmatter: dict,
        content: str,
        body: str,
    ):
        self.file_path = file_path
        self.title = title
        self.note_type = note_type
        self.domain = domain
        self.kind = kind
        self.graph_layer = graph_layer
        self.graph_role = graph_role
        self.verification = verification
        self.status = status
        self.frontmatter = frontmatter
        self.content = content
        self.body = body

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "title": self.title,
            "type": self.note_type,
            "domain": self.domain,
            "kind": self.kind,
            "graph_layer": self.graph_layer,
            "graph_role": self.graph_role,
            "verification": self.verification,
            "status": self.status,
            "frontmatter": self.frontmatter,
            "body": self.body,
        }


class NoteService:
    """High-level note reading service."""

    def __init__(self, db: DatabaseBackend, storage: LocalStorageBackend):
        self.db = db
        self.storage = storage

    def get_note(self, instance_id: str, file_path: str) -> NoteInfo | None:
        """Read a note, parse frontmatter, return structured content.

        Args:
            instance_id: Instance ID
            file_path: Relative path within the vault (e.g. "02-知识卡片/xxx.md")

        Returns:
            NoteInfo or None if not found
        """
        file_path = validate_vault_relative_path(file_path)

        # Get instance to find vault_path
        instances = self.db.execute(
            "SELECT vault_path FROM instances WHERE id = ?", (instance_id,)
        )
        if not instances:
            raise InstanceNotFoundError(f"Instance {instance_id} not found")

        vault_path = instances[0]["vault_path"]

        # Read file from storage
        try:
            content = self.storage.read_file(str(resolve_vault_relative_path(vault_path, file_path)))
        except Exception:
            return None

        # Parse frontmatter
        frontmatter, body = parse_frontmatter(content)

        # Get index metadata if available
        index_rows = self.db.execute(
            """SELECT title, type, domain, kind, graph_layer, graph_role,
                      verification, status
               FROM notes
               WHERE instance_id = ? AND file_path = ?""",
            (instance_id, file_path),
        )

        if index_rows:
            row = index_rows[0]
            return NoteInfo(
                file_path=file_path,
                title=row.get("title", frontmatter.get("title", "")),
                note_type=row.get("type", frontmatter.get("type", "")),
                domain=row.get("domain"),
                kind=row.get("kind"),
                graph_layer=row.get("graph_layer", 0),
                graph_role=row.get("graph_role"),
                verification=row.get("verification", "unverified"),
                status=row.get("status", "active"),
                frontmatter=frontmatter,
                content=content,
                body=body,
            )

        # Not indexed yet, return from file only
        return NoteInfo(
            file_path=file_path,
            title=frontmatter.get("title", Path(file_path).stem),
            note_type=frontmatter.get("type", ""),
            domain=frontmatter.get("domain"),
            kind=frontmatter.get("kind"),
            graph_layer=frontmatter.get("graph_layer", 0),
            graph_role=frontmatter.get("graph_role"),
            verification=frontmatter.get("verification", "unverified"),
            status=frontmatter.get("status", "active"),
            frontmatter=frontmatter,
            content=content,
            body=body,
        )

    def list_notes(
        self,
        instance_id: str,
        note_type: str | None = None,
        domain: str | None = None,
        kind: str | None = None,
        graph_layer: int | None = None,
        verification: str | None = None,
        query: str | None = None,
    ) -> list[dict]:
        """List notes with optional filters."""
        sql = """SELECT file_path, title, type, domain, kind, graph_layer, graph_role,
                        verification, status, frontmatter, indexed_at
                 FROM notes
                 WHERE instance_id = ?"""
        params: list = [instance_id]

        if note_type:
            sql += " AND type = ?"
            params.append(note_type)
        if domain:
            sql += """ AND (
                domain = ?
                OR EXISTS (
                    SELECT 1 FROM note_facets nf
                    WHERE nf.instance_id = notes.instance_id
                      AND nf.file_path = notes.file_path
                      AND nf.field = 'domain'
                      AND nf.value = ?
                )
            )"""
            params.extend([domain, domain])
        if kind:
            sql += """ AND (
                kind = ?
                OR EXISTS (
                    SELECT 1 FROM note_facets nf
                    WHERE nf.instance_id = notes.instance_id
                      AND nf.file_path = notes.file_path
                      AND nf.field = 'kind'
                      AND nf.value = ?
                )
            )"""
            params.extend([kind, kind])
        if graph_layer is not None:
            sql += " AND graph_layer = ?"
            params.append(graph_layer)
        if verification:
            sql += " AND verification = ?"
            params.append(verification)
        if query:
            like = f"%{query.strip().lower()}%"
            sql += """ AND (
                lower(title) LIKE ?
                OR lower(file_path) LIKE ?
                OR lower(coalesce(frontmatter, '')) LIKE ?
                OR EXISTS (
                    SELECT 1 FROM note_facets nf
                    WHERE nf.instance_id = notes.instance_id
                      AND nf.file_path = notes.file_path
                      AND lower(nf.value) LIKE ?
                )
            )"""
            params.extend([like, like, like, like])

        sql += " ORDER BY title"
        rows = self.db.execute(sql, params)
        notes: list[dict] = []
        for row in rows:
            concepts: list[str] = []
            aliases: list[str] = []
            domain_values: list[str] = []
            kind_values: list[str] = []
            frontmatter: dict = {}
            try:
                frontmatter = json.loads(row.get("frontmatter") or "{}")
                raw_concepts = frontmatter.get("concepts", [])
                if isinstance(raw_concepts, list):
                    concepts = [str(item) for item in raw_concepts if item]
                aliases = _as_string_list(frontmatter.get("aliases", []))
                domain_values = _as_string_list(frontmatter.get("domain", []))
                kind_values = _as_string_list(frontmatter.get("kind", []))
            except (json.JSONDecodeError, TypeError):
                pass
            facets = self._facets_for_note(instance_id, row["file_path"])
            domain_values = facets.get("domain") or domain_values
            kind_values = facets.get("kind") or kind_values
            aliases = facets.get("aliases") or aliases

            notes.append({
                "file_path": normalize_vault_path(row["file_path"]),
                "title": row.get("title") or Path(row["file_path"]).stem,
                "type": row.get("type") or "",
                "domain": row.get("domain"),
                "kind": row.get("kind"),
                "graph_layer": row.get("graph_layer", 0),
                "graph_role": row.get("graph_role"),
                "verification": row.get("verification", "unverified"),
                "status": row.get("status", "active"),
                "concepts": concepts,
                "aliases": aliases,
                "domain_values": domain_values,
                "kind_values": kind_values,
                "facets": facets,
                "quality_warnings": _quality_warnings(row, frontmatter),
                "indexed_at": row.get("indexed_at"),
            })
        return notes

    def list_facets(self, instance_id: str) -> dict[str, list[str]]:
        """List normalized facet values for the current instance."""
        rows = self.db.execute(
            """SELECT field, value
               FROM note_facets
               WHERE instance_id = ?
               GROUP BY field, value
               ORDER BY field, lower(value)""",
            (instance_id,),
        )
        facets: dict[str, list[str]] = {}
        for row in rows:
            facets.setdefault(row["field"], []).append(row["value"])
        return facets

    def update_verification(self, instance_id: str, file_path: str, verification: str) -> NoteInfo | None:
        """Update a note's verification frontmatter and refresh its index."""
        file_path = validate_vault_relative_path(file_path)
        instances = self.db.execute(
            "SELECT vault_path FROM instances WHERE id = ?", (instance_id,)
        )
        if not instances:
            raise InstanceNotFoundError(f"Instance {instance_id} not found")

        vault_path = instances[0]["vault_path"]
        full_path = str(resolve_vault_relative_path(vault_path, file_path))

        try:
            content = self.storage.read_file(full_path)
        except Exception:
            return None

        frontmatter, body = parse_frontmatter(content)
        frontmatter["verification"] = verification
        updated_content = serialize_frontmatter(frontmatter, body)
        self.storage.write_file(full_path, updated_content)
        Indexer(self.db).index_note(instance_id, file_path, updated_content)
        invalidate_query_caches(instance_id)
        return self.get_note(instance_id, file_path)

    def update_metadata(
        self,
        instance_id: str,
        file_path: str,
        updates: dict[str, str | None],
    ) -> NoteInfo | None:
        """Update editable frontmatter fields and refresh the note index."""
        file_path = validate_vault_relative_path(file_path)
        instances = self.db.execute(
            "SELECT vault_path FROM instances WHERE id = ?", (instance_id,)
        )
        if not instances:
            raise InstanceNotFoundError(f"Instance {instance_id} not found")

        vault_path = instances[0]["vault_path"]
        full_path = str(resolve_vault_relative_path(vault_path, file_path))

        try:
            content = self.storage.read_file(full_path)
        except Exception:
            return None

        frontmatter, body = parse_frontmatter(content)
        for field in ("domain", "kind"):
            if field not in updates:
                continue
            value = str(updates.get(field) or "").strip()
            if value:
                frontmatter[field] = value
            else:
                frontmatter.pop(field, None)

        if "verification" in updates:
            frontmatter["verification"] = str(updates["verification"]).strip()

        updated_content = serialize_frontmatter(frontmatter, body)
        self.storage.write_file(full_path, updated_content)
        Indexer(self.db).index_note(instance_id, file_path, updated_content)
        invalidate_query_caches(instance_id)
        return self.get_note(instance_id, file_path)

    def delete_note(self, instance_id: str, file_path: str) -> bool:
        """Delete a note file and remove its index entries."""
        file_path = validate_vault_relative_path(file_path)
        instances = self.db.execute(
            "SELECT vault_path FROM instances WHERE id = ?", (instance_id,)
        )
        if not instances:
            raise InstanceNotFoundError(f"Instance {instance_id} not found")

        vault_path = instances[0]["vault_path"]
        full_path = str(resolve_vault_relative_path(vault_path, file_path))
        indexed = self.db.execute(
            "SELECT 1 FROM notes WHERE instance_id = ? AND file_path = ? LIMIT 1",
            (instance_id, file_path),
        )
        file_exists = self.storage.exists(full_path)
        if not indexed and not file_exists:
            return False

        if file_exists:
            self.storage.delete_file(full_path)
        Indexer(self.db).remove_note(instance_id, file_path)
        invalidate_query_caches(instance_id)
        return True

    def _facets_for_note(self, instance_id: str, file_path: str) -> dict[str, list[str]]:
        rows = self.db.execute(
            """SELECT field, value
               FROM note_facets
               WHERE instance_id = ? AND file_path = ?
               ORDER BY field, lower(value)""",
            (instance_id, normalize_vault_path(file_path)),
        )
        facets: dict[str, list[str]] = {}
        for row in rows:
            facets.setdefault(row["field"], []).append(row["value"])
        return facets


def _as_string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if value:
        return [str(value)]
    return []


def _quality_warnings(row: dict, frontmatter: dict) -> list[str]:
    warnings: list[str] = []
    metadata_warnings = frontmatter.get("metadata_warnings", [])
    if isinstance(metadata_warnings, list):
        warnings.extend(str(item) for item in metadata_warnings if item)
    graph_layer = int(row.get("graph_layer") or 0)
    if graph_layer == 2 and not _as_string_list(frontmatter.get("sources", [])):
        warnings.append("missing_sources")
    if graph_layer == 3 and not (frontmatter.get("core_concepts") or frontmatter.get("reading_path")):
        warnings.append("weak_map_structure")
    if row.get("verification") in (None, "", "unverified", "draft"):
        warnings.append("needs_review")
    return list(dict.fromkeys(warnings))
