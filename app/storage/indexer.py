"""Indexer - maintains notes table, FTS index, and relations."""

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from app.pipeline.relation_builder import extract_link_references
from app.schema.map_parser import MAP_STRUCTURE_FIELDS, parse_map_body_sections
from app.schema.metadata_normalizer import clean_wikilink_target, normalize_metadata
from app.schema.parser import parse_frontmatter
from app.storage.database import DatabaseBackend
from app.storage.path_utils import normalize_vault_path

logger = logging.getLogger(__name__)


class Indexer:
    """Manages SQLite index for knowledge notes."""

    def __init__(self, db: DatabaseBackend):
        self.db = db

    def index_note(
        self,
        instance_id: str,
        file_path: str,
        content: str,
    ) -> int:
        """Parse a note and insert/update its index entry.

        Returns the note row ID.
        """
        # Normalize vault-relative paths for cross-platform consistency.
        file_path = normalize_vault_path(file_path)
        raw_frontmatter, body = parse_frontmatter(content)
        raw_frontmatter = _merge_map_markdown_structure(raw_frontmatter, body)
        metadata = normalize_metadata(raw_frontmatter)
        frontmatter = metadata.frontmatter
        title = self._extract_title(content, frontmatter, file_path)
        content_hash = hashlib.md5(content.encode()).hexdigest()
        now = datetime.now(UTC).isoformat()
        index_text = self._build_index_text(title, frontmatter, metadata.search_terms, body)

        # Upsert into notes table
        existing = self.db.execute(
            "SELECT id, title, search_text FROM notes WHERE instance_id = ? AND file_path = ?",
            (instance_id, file_path),
        )

        if existing:
            note_id = existing[0]["id"]
            self._delete_fts_row(note_id, existing[0].get("title") or "", existing[0].get("search_text") or "")
            self.db.execute(
                """UPDATE notes SET title=?, type=?, domain=?, kind=?, graph_layer=?,
                   graph_role=?, verification=?, status=?, frontmatter=?,
                   search_text=?, content_hash=?, indexed_at=?
                   WHERE instance_id=? AND file_path=?""",
                (
                    title,
                    frontmatter.get("type"),
                    metadata.first("domain"),
                    metadata.first("kind"),
                    frontmatter.get("graph_layer", 0),
                    frontmatter.get("graph_role"),
                    frontmatter.get("verification", "unverified"),
                    frontmatter.get("status", "active"),
                    json.dumps(frontmatter, ensure_ascii=False),
                    index_text,
                    content_hash,
                    now,
                    instance_id,
                    file_path,
                ),
            )
        else:
            self.db.execute(
                """INSERT INTO notes (instance_id, file_path, title, type, domain, kind,
                   graph_layer, graph_role, verification, status, frontmatter,
                   search_text, content_hash, indexed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    instance_id,
                    file_path,
                    title,
                    frontmatter.get("type"),
                    metadata.first("domain"),
                    metadata.first("kind"),
                    frontmatter.get("graph_layer", 0),
                    frontmatter.get("graph_role"),
                    frontmatter.get("verification", "unverified"),
                    frontmatter.get("status", "active"),
                    json.dumps(frontmatter, ensure_ascii=False),
                    index_text,
                    content_hash,
                    now,
                ),
            )
            note_id = self.db.execute(
                "SELECT id FROM notes WHERE instance_id = ? AND file_path = ?",
                (instance_id, file_path),
            )[0]["id"]

        self._update_facets(instance_id, file_path, metadata.facets)
        self._update_link_references(instance_id, file_path, body, frontmatter)
        self._insert_fts_row(note_id, title, index_text)

        return note_id

    def remove_note(self, instance_id: str, file_path: str) -> None:
        """Remove a note from the index.

        TODO: This method does not clean up the note_embeddings table because the
        Indexer does not have access to SemanticIndex. This can lead to orphaned
        embeddings in note_embeddings for deleted notes. A callback mechanism or
        shared reference to SemanticIndex should be added to ensure embeddings are
        cleaned up when notes are removed.
        """
        existing = self.db.execute(
            "SELECT id, title, search_text FROM notes WHERE instance_id = ? AND file_path = ?",
            (instance_id, file_path),
        )
        if existing:
            note_id = existing[0]["id"]
            old_title = existing[0]["title"]
            old_search_text = existing[0].get("search_text") or ""
            self._delete_fts_row(note_id, old_title, old_search_text)
            self.db.execute(
                "DELETE FROM notes WHERE instance_id = ? AND file_path = ?",
                (instance_id, file_path),
            )
            self.db.execute(
                "DELETE FROM note_facets WHERE instance_id = ? AND file_path = ?",
                (instance_id, file_path),
            )
            self.db.execute(
                """DELETE FROM link_references
                   WHERE instance_id = ? AND (source_path = ? OR target_path = ?)""",
                (instance_id, file_path, file_path),
            )
            self.db.execute(
                """DELETE FROM relations
                   WHERE instance_id = ? AND (source_path = ? OR target_path = ?)""",
                (instance_id, file_path, file_path),
            )

    def index_relations(self, instance_id: str, relations: list[dict]) -> None:
        """Insert relation edges into the relations table (skips duplicates)."""
        if not relations:
            return
        # Normalize path separators to forward slash for cross-platform consistency
        self.db.executemany(
            """INSERT OR IGNORE INTO relations
               (instance_id, source_path, target_path, rel_type)
               VALUES (?, ?, ?, ?)""",
            [
                (
                    instance_id,
                    normalize_vault_path(r["source_path"]),
                    normalize_vault_path(r["target_path"]),
                    r["rel_type"],
                )
                for r in relations
            ],
        )

    def index_link_references(self, instance_id: str, references: list[dict]) -> None:
        """Insert diagnosable link references for an instance."""
        if not references:
            return
        self.db.executemany(
            """INSERT INTO link_references
               (instance_id, source_path, target_text, target_path, link_kind, source_field, resolved)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(instance_id, source_path, target_text, link_kind, source_field)
               DO UPDATE SET
                   target_path = excluded.target_path,
                   resolved = excluded.resolved""",
            [
                (
                    instance_id,
                    normalize_vault_path(ref["source_path"]),
                    str(ref["target_text"]),
                    normalize_vault_path(ref.get("target_path") or "") or None,
                    ref.get("link_kind", "wikilink"),
                    ref.get("source_field", "body"),
                    1 if ref.get("resolved") else 0,
                )
                for ref in references
            ],
        )

    def clear_instance_index(self, instance_id: str) -> None:
        """Clear all index data for an instance (used by reindex)."""
        self.db.execute("DELETE FROM relations WHERE instance_id = ?", (instance_id,))
        self.db.execute("DELETE FROM link_references WHERE instance_id = ?", (instance_id,))
        self.db.execute("DELETE FROM note_facets WHERE instance_id = ?", (instance_id,))
        notes = self.db.execute(
            "SELECT id, title, search_text FROM notes WHERE instance_id = ?", (instance_id,)
        )
        for row in notes:
            self._delete_fts_row(row["id"], row["title"], row.get("search_text") or "")
        self.db.execute("DELETE FROM notes WHERE instance_id = ?", (instance_id,))

    def _build_index_text(
        self,
        title: str,
        frontmatter: dict,
        search_terms: list[str],
        body: str,
    ) -> str:
        """Build the persisted text used by the external-content FTS table."""
        return " ".join(
            _dedupe_text([
                title,
                *search_terms,
                *_flatten_map_fields(frontmatter),
                *_extract_headings(body),
                *_extract_index_windows(frontmatter, body),
            ])
        )

    def _delete_fts_row(self, note_id: int, title: str, search_text: str) -> None:
        """Delete an FTS row before mutating/deleting its external content row."""
        try:
            self.db.execute(
                "INSERT INTO notes_fts(notes_fts, rowid, title, search_text) VALUES('delete', ?, ?, ?)",
                (note_id, title, search_text),
            )
        except Exception:
            pass

    def _insert_fts_row(self, note_id: int, title: str, search_text: str) -> None:
        """Insert the current note values into the FTS index."""
        self.db.execute(
            "INSERT INTO notes_fts(rowid, title, search_text) VALUES(?, ?, ?)",
            (note_id, title, search_text),
        )

    def _extract_title(self, content: str, frontmatter: dict, file_path: str) -> str:
        """Extract title from content or file path."""
        # Try H1 heading
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
        # Fallback to filename
        return Path(file_path).stem

    def _update_facets(
        self,
        instance_id: str,
        file_path: str,
        facets: list[tuple[str, str]],
    ) -> None:
        """Replace normalized metadata facets for a note."""
        self.db.execute(
            "DELETE FROM note_facets WHERE instance_id = ? AND file_path = ?",
            (instance_id, file_path),
        )
        if not facets:
            return
        self.db.executemany(
            """INSERT OR IGNORE INTO note_facets (instance_id, file_path, field, value)
               VALUES (?, ?, ?, ?)""",
            [
                (instance_id, file_path, field, value)
                for field, value in facets
            ],
        )

    def _update_link_references(
        self,
        instance_id: str,
        file_path: str,
        body: str,
        frontmatter: dict,
    ) -> None:
        """Replace body/frontmatter link references for a note."""
        self.db.execute(
            "DELETE FROM link_references WHERE instance_id = ? AND source_path = ?",
            (instance_id, file_path),
        )
        raw_frontmatter = frontmatter.get("raw_frontmatter", frontmatter)
        references = extract_link_references(
            content=body,
            frontmatter=raw_frontmatter if isinstance(raw_frontmatter, dict) else frontmatter,
            source_path=file_path,
            resolver=lambda target: self._resolve_link_target_from_db(instance_id, target),
        )
        self.index_link_references(instance_id, references)

    def _resolve_link_target_from_db(self, instance_id: str, target: str) -> str:
        """Resolve a wikilink target against already indexed notes in the same instance."""
        target = clean_wikilink_target(target)
        normalized_target = normalize_vault_path(target)
        stem = Path(normalized_target).stem
        target_lower = normalized_target.lower()
        stem_lower = stem.lower()

        rows = self.db.execute(
            """SELECT file_path
               FROM notes
               WHERE instance_id = ?
                 AND (
                    lower(file_path) = ?
                    OR lower(file_path) = ?
                    OR lower(file_path) LIKE ?
                    OR lower(title) = ?
                 )
               ORDER BY CASE WHEN lower(title) = ? THEN 0 ELSE 1 END
               LIMIT 1""",
            (
                instance_id,
                target_lower,
                f"{stem_lower}.md",
                f"%/{stem_lower}.md",
                stem_lower,
                stem_lower,
            ),
        )
        if rows:
            return normalize_vault_path(rows[0]["file_path"])

        facet_rows = self.db.execute(
            """SELECT file_path
               FROM note_facets
               WHERE instance_id = ?
                 AND field IN ('aliases', 'concepts')
                 AND lower(value) = ?
               ORDER BY CASE WHEN field = 'aliases' THEN 0 ELSE 1 END
               LIMIT 1""",
            (instance_id, stem_lower),
        )
        return normalize_vault_path(facet_rows[0]["file_path"]) if facet_rows else ""


def _flatten_map_fields(frontmatter: dict) -> list[str]:
    """Flatten v4 map structured frontmatter into searchable text."""
    if int(frontmatter.get("graph_layer") or 0) != 3:
        return []

    values: list[str] = []
    for field in [
        "core_concepts",
        "reading_path",
        "key_relations",
        "source_materials",
        "linked_maps",
    ]:
        _append_search_values(frontmatter.get(field), values)
    return values


def _merge_map_markdown_structure(frontmatter: dict, body: str) -> dict:
    """Merge v4 map structure parsed from body into frontmatter for indexing."""
    try:
        graph_layer = int(frontmatter.get("graph_layer") or 0)
    except (TypeError, ValueError):
        graph_layer = 0
    if graph_layer != 3:
        return frontmatter

    parsed = parse_map_body_sections(body)
    merged = dict(frontmatter)
    for field in MAP_STRUCTURE_FIELDS:
        if not merged.get(field) and parsed.get(field):
            merged[field] = parsed[field]
    return merged


def _append_search_values(value, values: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        if value:
            values.append(value)
        return
    if isinstance(value, (int, float)):
        values.append(str(value))
        return
    if isinstance(value, list):
        for item in value:
            _append_search_values(item, values)
        return
    if isinstance(value, dict):
        for item in value.values():
            _append_search_values(item, values)


def _extract_headings(body: str) -> list[str]:
    """Extract searchable heading text from the note body."""
    headings: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        text = stripped.lstrip("#").strip()
        if text:
            headings.append(text)
        if len(headings) >= 40:
            break
    return headings


def _extract_index_windows(frontmatter: dict, body: str) -> list[str]:
    """Extract bounded definition/summary/question windows for FTS recall."""
    graph_layer = int(frontmatter.get("graph_layer") or 0)
    max_items = 8 if graph_layer in (1, 2) else 5
    max_len = 240 if graph_layer in (1, 2) else 180
    keywords = (
        "摘要",
        "定义",
        "结论",
        "问题",
        "回答",
        "summary",
        "definition",
        "conclusion",
        "question",
        "answer",
    )
    windows: list[str] = []
    current_heading = ""
    for line in body.splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("#"):
            current_heading = text.lstrip("#").strip().lower()
            continue
        haystack = f"{current_heading} {text}".lower()
        if any(keyword in haystack for keyword in keywords):
            windows.append(text[:max_len])
        if len(windows) >= max_items:
            break
    return windows


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
