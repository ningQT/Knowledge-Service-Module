"""Instance-scoped diagnostics for KSM knowledge bases."""

from __future__ import annotations

import json
from pathlib import Path

from app.storage.database import DatabaseBackend
from app.storage.path_utils import normalize_vault_path


class DiagnosticsService:
    """Build actionable diagnostics strictly within one knowledge-base instance."""

    def __init__(self, db: DatabaseBackend):
        self.db = db

    def get_diagnostics(self, instance_id: str) -> dict:
        """Return summary counts and an actionable issue list."""
        notes = self.db.execute(
            """SELECT file_path, title, type, graph_layer, verification, frontmatter
               FROM notes
               WHERE instance_id = ?
               ORDER BY title""",
            (instance_id,),
        )
        issues: list[dict] = []
        issues.extend(self._unresolved_link_issues(instance_id))
        issues.extend(self._isolated_node_issues(instance_id, notes))
        issues.extend(self._missing_source_issues(instance_id, notes))
        issues.extend(self._field_warning_issues(notes))
        issues.extend(self._weak_map_issues(notes))

        total_notes = len(notes)
        unreviewed = sum(1 for note in notes if note.get("verification") != "verified")
        unreviewed_ratio = (unreviewed / total_notes) if total_notes else 0.0
        if total_notes and unreviewed_ratio >= 0.5:
            issues.append({
                "code": "high_unreviewed_ratio",
                "severity": "info",
                "title": "Many notes are not reviewed",
                "message": f"{unreviewed} of {total_notes} notes are not marked reviewed.",
                "file_path": None,
                "details": {"ratio": unreviewed_ratio, "count": unreviewed},
            })

        summary = {
            "total_notes": total_notes,
            "issue_count": len(issues),
            "unresolved_links": _count_code(issues, "unresolved_link"),
            "isolated_nodes": _count_code(issues, "isolated_node"),
            "missing_sources": _count_code(issues, "missing_sources"),
            "field_warnings": _count_code(issues, "field_warning"),
            "weak_maps": _count_code(issues, "weak_map_structure"),
            "unreviewed_ratio": unreviewed_ratio,
        }
        return {"instance_id": instance_id, "summary": summary, "issues": issues}

    def _unresolved_link_issues(self, instance_id: str) -> list[dict]:
        rows = self.db.execute(
            """SELECT source_path, target_text, source_field, link_kind
               FROM link_references
               WHERE instance_id = ? AND resolved = 0
               ORDER BY source_path, target_text""",
            (instance_id,),
        )
        issues: list[dict] = []
        for row in rows:
            if self._resolve_reference(instance_id, row["target_text"]):
                continue
            issues.append({
                "code": "unresolved_link",
                "severity": "warning",
                "title": "Unresolved link",
                "message": f"{row['source_path']} references {row['target_text']}, but no note resolves it.",
                "file_path": normalize_vault_path(row["source_path"]),
                "details": {
                    "target_text": row["target_text"],
                    "source_field": row["source_field"],
                    "link_kind": row["link_kind"],
                },
            })
        return issues

    def _isolated_node_issues(self, instance_id: str, notes: list[dict]) -> list[dict]:
        issues: list[dict] = []
        for note in notes:
            path = normalize_vault_path(note["file_path"])
            rows = self.db.execute(
                """SELECT 1
                   FROM relations
                   WHERE instance_id = ?
                     AND (source_path = ? OR target_path = ?)
                   LIMIT 1""",
                (instance_id, path, path),
            )
            if rows:
                continue
            issues.append({
                "code": "isolated_node",
                "severity": "info",
                "title": "Isolated note",
                "message": f"{note['title']} has no resolved graph relation.",
                "file_path": path,
                "details": {"title": note["title"], "graph_layer": note.get("graph_layer", 0)},
            })
        return issues

    def _missing_source_issues(self, instance_id: str, notes: list[dict]) -> list[dict]:
        issues: list[dict] = []
        for note in notes:
            if int(note.get("graph_layer") or 0) != 2:
                continue
            frontmatter = _loads_frontmatter(note)
            sources = frontmatter.get("sources", [])
            if sources:
                continue
            rel_rows = self.db.execute(
                """SELECT 1
                   FROM relations
                   WHERE instance_id = ?
                     AND source_path = ?
                     AND rel_type = 'source_trace'
                   LIMIT 1""",
                (instance_id, normalize_vault_path(note["file_path"])),
            )
            if rel_rows:
                continue
            issues.append({
                "code": "missing_sources",
                "severity": "warning",
                "title": "Card has no source",
                "message": f"{note['title']} has no source metadata or source_trace relation.",
                "file_path": normalize_vault_path(note["file_path"]),
                "details": {"title": note["title"]},
            })
        return issues

    def _field_warning_issues(self, notes: list[dict]) -> list[dict]:
        issues: list[dict] = []
        for note in notes:
            frontmatter = _loads_frontmatter(note)
            warnings = frontmatter.get("metadata_warnings", [])
            if not isinstance(warnings, list):
                continue
            for warning in warnings:
                issues.append({
                    "code": "field_warning",
                    "severity": "info",
                    "title": "Metadata normalized",
                    "message": f"{note['title']} has metadata warning: {warning}.",
                    "file_path": normalize_vault_path(note["file_path"]),
                    "details": {"warning": warning},
                })
        return issues

    def _weak_map_issues(self, notes: list[dict]) -> list[dict]:
        issues: list[dict] = []
        for note in notes:
            if int(note.get("graph_layer") or 0) != 3:
                continue
            frontmatter = _loads_frontmatter(note)
            if frontmatter.get("core_concepts") or frontmatter.get("reading_path"):
                continue
            issues.append({
                "code": "weak_map_structure",
                "severity": "warning",
                "title": "Map structure is thin",
                "message": f"{note['title']} is missing core concepts and reading path structure.",
                "file_path": normalize_vault_path(note["file_path"]),
                "details": {"title": note["title"]},
            })
        return issues

    def _resolve_reference(self, instance_id: str, target_text: str) -> str:
        target = normalize_vault_path(str(target_text or "").strip())
        stem = Path(target).stem
        target_lower = target.lower()
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
               LIMIT 1""",
            (instance_id, target_lower, f"{stem_lower}.md", f"%/{stem_lower}.md", stem_lower),
        )
        if rows:
            return normalize_vault_path(rows[0]["file_path"])
        facet_rows = self.db.execute(
            """SELECT file_path
               FROM note_facets
               WHERE instance_id = ?
                 AND field IN ('aliases', 'concepts')
                 AND lower(value) = ?
               LIMIT 1""",
            (instance_id, stem_lower),
        )
        return normalize_vault_path(facet_rows[0]["file_path"]) if facet_rows else ""


def _loads_frontmatter(note: dict) -> dict:
    try:
        value = note.get("frontmatter") or "{}"
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return {}


def _count_code(issues: list[dict], code: str) -> int:
    return sum(1 for issue in issues if issue.get("code") == code)
