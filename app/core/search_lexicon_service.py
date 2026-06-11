"""Instance-scoped search lexicon service."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.pipeline.query_dictionary import invalidate_query_caches
from app.storage.database import DatabaseBackend

RELATION_TYPES = {"alias", "synonym"}
MAX_VARIANT_TERMS = 50


class SearchLexiconValidationError(ValueError):
    """Raised when lexicon input is invalid."""


class SearchLexiconDuplicateError(ValueError):
    """Raised when a canonical term already exists in the same instance/type."""


class SearchLexiconNotFoundError(ValueError):
    """Raised when a lexicon entry is not found."""


class SearchLexiconService:
    """CRUD service for instance-level search lexicon entries."""

    def __init__(self, db: DatabaseBackend):
        self.db = db

    def list_entries(self, instance_id: str) -> list[dict[str, Any]]:
        self._ensure_instance(instance_id)
        rows = self.db.execute(
            """SELECT id, instance_id, relation_type, canonical_term, variant_terms_json,
                      enabled, notes, created_at, updated_at
               FROM instance_search_lexicon
               WHERE instance_id = ?
               ORDER BY relation_type, lower(canonical_term), created_at""",
            (instance_id,),
        )
        return [_row_to_entry(row) for row in rows]

    def create_entry(
        self,
        instance_id: str,
        *,
        relation_type: str,
        canonical_term: str,
        variant_terms: list[str],
        enabled: bool = True,
        notes: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_instance(instance_id)
        relation_type = _normalize_relation_type(relation_type)
        canonical = _normalize_term(canonical_term, field="canonical_term")
        variants = _normalize_variants(variant_terms, canonical)
        self._ensure_unique(instance_id, relation_type, canonical, variants, exclude_id=None)

        now = datetime.now(UTC).isoformat()
        entry_id = f"lex_{uuid.uuid4().hex[:12]}"
        self.db.execute(
            """INSERT INTO instance_search_lexicon
               (id, instance_id, relation_type, canonical_term, canonical_term_norm,
                variant_terms_json, enabled, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id,
                instance_id,
                relation_type,
                canonical,
                _term_key(canonical),
                json.dumps(variants, ensure_ascii=False),
                1 if enabled else 0,
                (notes or "").strip(),
                now,
                now,
            ),
        )
        invalidate_query_caches(instance_id)
        return self.get_entry(instance_id, entry_id)

    def update_entry(
        self,
        instance_id: str,
        entry_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        current = self.get_entry(instance_id, entry_id)
        relation_type = _normalize_relation_type(updates.get("relation_type", current["relation_type"]))
        canonical = _normalize_term(
            updates.get("canonical_term", current["canonical_term"]),
            field="canonical_term",
        )
        variants_value = updates.get("variant_terms", current["variant_terms"])
        variants = _normalize_variants(variants_value, canonical)
        enabled = bool(updates.get("enabled", current["enabled"]))
        notes = str(updates.get("notes", current["notes"]) or "").strip()
        self._ensure_unique(instance_id, relation_type, canonical, variants, exclude_id=entry_id)

        now = datetime.now(UTC).isoformat()
        self.db.execute(
            """UPDATE instance_search_lexicon
               SET relation_type = ?, canonical_term = ?, canonical_term_norm = ?,
                   variant_terms_json = ?, enabled = ?, notes = ?, updated_at = ?
               WHERE instance_id = ? AND id = ?""",
            (
                relation_type,
                canonical,
                _term_key(canonical),
                json.dumps(variants, ensure_ascii=False),
                1 if enabled else 0,
                notes,
                now,
                instance_id,
                entry_id,
            ),
        )
        invalidate_query_caches(instance_id)
        return self.get_entry(instance_id, entry_id)

    def delete_entry(self, instance_id: str, entry_id: str) -> None:
        self._ensure_instance(instance_id)
        rows = self.db.execute(
            "SELECT id FROM instance_search_lexicon WHERE instance_id = ? AND id = ?",
            (instance_id, entry_id),
        )
        if not rows:
            raise SearchLexiconNotFoundError("Search lexicon entry not found")
        self.db.execute(
            "DELETE FROM instance_search_lexicon WHERE instance_id = ? AND id = ?",
            (instance_id, entry_id),
        )
        invalidate_query_caches(instance_id)

    def get_entry(self, instance_id: str, entry_id: str) -> dict[str, Any]:
        self._ensure_instance(instance_id)
        rows = self.db.execute(
            """SELECT id, instance_id, relation_type, canonical_term, variant_terms_json,
                      enabled, notes, created_at, updated_at
               FROM instance_search_lexicon
               WHERE instance_id = ? AND id = ?""",
            (instance_id, entry_id),
        )
        if not rows:
            raise SearchLexiconNotFoundError("Search lexicon entry not found")
        return _row_to_entry(rows[0])

    def _ensure_instance(self, instance_id: str) -> None:
        rows = self.db.execute("SELECT id FROM instances WHERE id = ?", (instance_id,))
        if not rows:
            raise SearchLexiconNotFoundError(f"Instance {instance_id} not found")

    def _ensure_unique(
        self,
        instance_id: str,
        relation_type: str,
        canonical_term: str,
        variant_terms: list[str],
        *,
        exclude_id: str | None,
    ) -> None:
        requested_terms = {_term_key(canonical_term), *[_term_key(term) for term in variant_terms]}
        params: list[Any] = [instance_id, relation_type]
        sql = """SELECT id, canonical_term, variant_terms_json FROM instance_search_lexicon
                 WHERE instance_id = ?
                   AND relation_type = ?"""
        if exclude_id:
            sql += " AND id != ?"
            params.append(exclude_id)
        rows = self.db.execute(sql, params)
        for row in rows:
            existing_terms = {_term_key(row["canonical_term"])}
            existing_terms.update(_term_key(term) for term in _load_variants(row.get("variant_terms_json")))
            if requested_terms & existing_terms:
                raise SearchLexiconDuplicateError("Search lexicon entry already exists")


def _row_to_entry(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "instance_id": row["instance_id"],
        "relation_type": row["relation_type"],
        "canonical_term": row["canonical_term"],
        "variant_terms": _load_variants(row.get("variant_terms_json")),
        "enabled": bool(row.get("enabled")),
        "notes": row.get("notes") or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _normalize_relation_type(value: str) -> str:
    text = str(value or "").strip().lower()
    if text not in RELATION_TYPES:
        raise SearchLexiconValidationError("relation_type must be alias or synonym")
    return text


def _normalize_term(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SearchLexiconValidationError(f"{field} is required")
    return text


def _normalize_variants(values: Any, canonical: str) -> list[str]:
    if values is None:
        values = []
    if not isinstance(values, list):
        raise SearchLexiconValidationError("variant_terms must be a list")
    seen = {_term_key(canonical)}
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = _term_key(text)
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    if len(result) > MAX_VARIANT_TERMS:
        raise SearchLexiconValidationError("variant_terms exceeds limit")
    return result


def _load_variants(value: Any) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item or "").strip()]


def _term_key(value: str) -> str:
    return " ".join(str(value or "").strip().casefold().split())
