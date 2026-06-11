"""Map-priority search path for v4 retrieval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.pipeline.candidate_organizer import organize_candidates
from app.pipeline.graph_expander import graph_expansion
from app.pipeline.node_key import node_key as _node_key, row_key as _row_key
from app.schema.map_parser import (
    has_map_structure,
    parse_map_structure,
    structure_from_frontmatter,
)
from app.storage.database import DatabaseBackend

NOTE_FIELDS = (
    "instance_id, file_path, title, graph_layer, graph_role, domain, kind, "
    "verification, frontmatter"
)


def discover_map_entry(query_context: dict, db: DatabaseBackend) -> dict | None:
    """Discover the best verified map entry using M1-M4 channels."""
    candidates = query_context.get("concept_candidates", [])
    instance_ids = query_context.get("instance_ids", [])
    domain_hint = query_context.get("domain_hint")
    if not instance_ids:
        return None

    results: list[dict] = []
    results.extend(_map_title_matches(candidates, instance_ids, db))
    results.extend(_map_concepts_matches(candidates, instance_ids, db))
    results.extend(_map_fts_matches(candidates, instance_ids, db))
    if domain_hint:
        fallback = _map_domain_fallback(domain_hint, instance_ids, db)
        if fallback:
            results.append(fallback)

    if not results:
        return None

    best: dict[str, dict] = {}
    for item in results:
        path = _node_key(item)
        if path not in best or item["score"] > best[path]["score"]:
            best[path] = item
    return sorted(best.values(), key=lambda x: x["score"], reverse=True)[0]


def parse_map_markdown(content: str) -> dict:
    """Parse v4 map structure from frontmatter first, then standard markdown sections."""
    return parse_map_structure(content)


def expand_map_structure(
    map_entry: dict,
    query_context: dict,
    db: DatabaseBackend,
) -> dict | None:
    """Expand map structured fields into card/source/map candidates."""
    structure = structure_from_frontmatter(map_entry.get("frontmatter", {}))
    if not has_map_structure(structure):
        return None

    instance_ids = query_context.get("instance_ids", [])
    card_anchors: list[dict] = []
    card_roles: dict[str, str] = {}
    reading_paths: set[str] = set()
    reading_cards: list[dict] = []

    for item in structure["core_concepts"]:
        note = _resolve_note(item, instance_ids, db, layer=2)
        if not note:
            continue
        role = _item_role(item)
        note.update({
            "score": _role_score(role),
            "match_type": "map_core_concept",
            "match_keyword": _item_title(item),
            "map_sourced": True,
            "source_map": map_entry["path"],
            "map_role": role,
        })
        card_roles[_node_key(note)] = role
        card_anchors.append(note)

    for item in structure["reading_path"]:
        note = _resolve_note(item, instance_ids, db, layer=2)
        if not note:
            continue
        note_key = _node_key(note)
        reading_paths.add(note_key)
        if note_key in {_node_key(anchor) for anchor in card_anchors}:
            continue
        note.update({
            "score": 0.82,
            "match_type": "map_reading_path",
            "match_keyword": _item_title(item),
            "map_sourced": True,
            "source_map": map_entry["path"],
            "map_role": "normal",
            "from_reading_path": True,
        })
        reading_cards.append(note)

    if not card_anchors:
        return None

    source_notes = [
        _mark_map_node(note, map_entry["path"], from_map_materials=True)
        for note in (
            _resolve_note(item, instance_ids, db, layer=1)
            for item in structure["source_materials"]
        )
        if note
    ]
    linked_maps = [
        _mark_map_node(note, map_entry["path"])
        for note in (
            _resolve_note(item, instance_ids, db, layer=3)
            for item in structure["linked_maps"]
        )
        if note and _node_key(note) != _node_key(map_entry)
    ]

    return {
        "card_anchors": card_anchors,
        "card_roles": card_roles,
        "reading_paths": reading_paths,
        "reading_cards": reading_cards,
        "source_notes": source_notes,
        "linked_maps": linked_maps,
        "key_relations": structure["key_relations"],
    }


def organize_candidates_from_map(
    map_entry: dict,
    expansion_result: dict,
    expanded: dict,
) -> dict:
    """Organize map-priority candidates into the standard four result groups."""
    organized = organize_candidates(expanded["card_anchors"], expansion_result)
    source_map = map_entry["path"]
    reading_paths = expanded["reading_paths"]
    card_roles = expanded["card_roles"]

    for group in ("core_hits", "related_cards"):
        for node in organized[group]:
            node["map_sourced"] = True
            node["source_map"] = source_map
            node["map_role"] = card_roles.get(_node_key(node), node.get("map_role", "normal"))
            if _node_key(node) in reading_paths:
                node["from_reading_path"] = True

    _merge_unique(organized["related_cards"], expanded["reading_cards"])
    _merge_unique(organized["source_notes"], expanded["source_notes"])
    primary_map = {
        **map_entry,
        "is_primary": True,
        "map_sourced": True,
        "source_map": source_map,
        "map_role": "primary",
    }
    organized["maps"].insert(0, primary_map)
    _merge_unique(organized["maps"], expanded["linked_maps"])
    return organized


def search_with_map_priority(
    query_context: dict,
    intent_type: str,
    instance_ids: list[str],
    max_depth: int,
    db: DatabaseBackend,
) -> dict | None:
    """Run the map-priority branch. Return None to downgrade to v3."""
    map_entry = discover_map_entry(query_context, db)
    if not map_entry:
        return None

    expanded = expand_map_structure(map_entry, query_context, db)
    if not expanded:
        return None

    expansion_result = graph_expansion(
        anchors=expanded["card_anchors"],
        intent_type=intent_type,
        instance_ids=instance_ids,
        max_depth=max_depth,
        db=db,
    )
    organized = organize_candidates_from_map(map_entry, expansion_result, expanded)
    return {
        "organized": organized,
        "key_relations": expanded["key_relations"],
        "map_entry": map_entry,
    }


def _map_title_matches(
    candidates: list[str],
    instance_ids: list[str],
    db: DatabaseBackend,
) -> list[dict]:
    if not candidates:
        return []
    placeholders = ",".join("?" * len(instance_ids))
    results: list[dict] = []
    lower_candidates = [candidate.lower() for candidate in candidates]
    candidate_ph = ",".join("?" * len(lower_candidates))
    rows = db.execute(
        f"""SELECT {NOTE_FIELDS}
            FROM notes
            WHERE instance_id IN ({placeholders})
              AND graph_layer = 3
              AND verification = 'verified'
              AND LOWER(title) IN ({candidate_ph})""",
        [*instance_ids, *lower_candidates],
    )
    for row in rows:
        results.append(
            _row_to_node(
                row,
                score=1.0,
                match_type="map_title_exact",
                keyword=row["title"],
            )
        )

    existing = {_node_key(item) for item in results}
    for candidate in candidates:
        if len(candidate) < 2:
            continue
        rows = db.execute(
            f"""SELECT {NOTE_FIELDS}
                FROM notes
                WHERE instance_id IN ({placeholders})
                  AND graph_layer = 3
                  AND verification = 'verified'
                  AND title LIKE ?""",
            [*instance_ids, f"%{candidate}%"],
        )
        for row in rows:
            row_key = _row_key(row)
            if row_key in existing:
                continue
            existing.add(row_key)
            results.append(
                _row_to_node(
                    row,
                    score=0.85,
                    match_type="map_title_contains",
                    keyword=candidate,
                )
            )
    return results


def _map_concepts_matches(
    candidates: list[str],
    instance_ids: list[str],
    db: DatabaseBackend,
) -> list[dict]:
    if not candidates:
        return []
    placeholders = ",".join("?" * len(instance_ids))
    candidate_ph = ",".join("?" * len(candidates))
    lower_candidates = [candidate.lower() for candidate in candidates]
    rows = []
    try:
        rows.extend(db.execute(
            f"""SELECT DISTINCT n.instance_id, n.file_path, n.title, n.graph_layer, n.graph_role,
                       n.domain, n.kind, n.verification, n.frontmatter
                FROM notes n, json_each(n.frontmatter, '$.concepts') AS je
                WHERE n.instance_id IN ({placeholders})
                  AND n.graph_layer = 3
                  AND n.verification = 'verified'
                  AND LOWER(je.value) IN ({candidate_ph})""",
            [*instance_ids, *lower_candidates],
        ))
    except Exception:
        pass
    try:
        rows.extend(db.execute(
            f"""SELECT DISTINCT n.instance_id, n.file_path, n.title, n.graph_layer, n.graph_role,
                       n.domain, n.kind, n.verification, n.frontmatter
                FROM notes n
                JOIN note_facets nf
                  ON nf.instance_id = n.instance_id
                 AND nf.file_path = n.file_path
                WHERE n.instance_id IN ({placeholders})
                  AND n.graph_layer = 3
                  AND n.verification = 'verified'
                  AND nf.field IN ('concepts', 'aliases')
                  AND LOWER(nf.value) IN ({candidate_ph})""",
            [*instance_ids, *lower_candidates],
        ))
    except Exception:
        pass
    rows = list({_row_key(row): row for row in rows}.values())
    return [
        _row_to_node(
            row,
            score=0.8,
            match_type="map_concepts",
            keyword=" ".join(candidates),
        )
        for row in rows
    ]


def _map_fts_matches(
    candidates: list[str],
    instance_ids: list[str],
    db: DatabaseBackend,
) -> list[dict]:
    if not candidates:
        return []
    try:
        rows = db.fts_search(" OR ".join(candidates), instance_ids, layer=3, limit=5)
    except Exception:
        return []
    return [
        _row_to_node(row, score=0.6, match_type="map_fts", keyword=" ".join(candidates))
        for row in rows
        if row.get("verification") == "verified"
    ]


def _map_domain_fallback(domain: str, instance_ids: list[str], db: DatabaseBackend) -> dict | None:
    placeholders = ",".join("?" * len(instance_ids))
    rows = db.execute(
        f"""SELECT {NOTE_FIELDS}
            FROM notes
            WHERE instance_id IN ({placeholders})
              AND graph_layer = 3
              AND verification = 'verified'
              AND domain = ?
            ORDER BY indexed_at DESC
            LIMIT 1""",
        [*instance_ids, domain],
    )
    if not rows:
        rows = db.execute(
            f"""SELECT {NOTE_FIELDS}
                FROM notes
                WHERE instance_id IN ({placeholders})
                  AND graph_layer = 3
                  AND verification = 'verified'
                  AND EXISTS (
                    SELECT 1 FROM note_facets nf
                    WHERE nf.instance_id = notes.instance_id
                      AND nf.file_path = notes.file_path
                      AND nf.field = 'domain'
                      AND nf.value = ?
                  )
                ORDER BY indexed_at DESC
                LIMIT 1""",
            [*instance_ids, domain],
        )
    if not rows:
        return None
    return _row_to_node(rows[0], score=0.4, match_type="map_domain_fallback", keyword=domain)


def _resolve_note(
    item: Any,
    instance_ids: list[str],
    db: DatabaseBackend,
    layer: int,
) -> dict | None:
    path = _item_path(item)
    title = _item_title(item)
    if path:
        note = _load_note_by_path(path, instance_ids, db, layer)
        if note:
            return note
    if title:
        return _load_note_by_title(title, instance_ids, db, layer)
    return None


def _load_note_by_path(
    path: str,
    instance_ids: list[str],
    db: DatabaseBackend,
    layer: int,
) -> dict | None:
    placeholders = ",".join("?" * len(instance_ids))
    rows = db.execute(
        f"""SELECT {NOTE_FIELDS}
            FROM notes
            WHERE instance_id IN ({placeholders})
              AND graph_layer = ?
              AND file_path = ?
            LIMIT 1""",
        [*instance_ids, layer, path],
    )
    return _row_to_node(rows[0]) if rows else None


def _load_note_by_title(
    title: str,
    instance_ids: list[str],
    db: DatabaseBackend,
    layer: int,
) -> dict | None:
    placeholders = ",".join("?" * len(instance_ids))
    rows = db.execute(
        f"""SELECT {NOTE_FIELDS}
            FROM notes
            WHERE instance_id IN ({placeholders})
              AND graph_layer = ?
              AND (title = ? OR title LIKE ?)
            ORDER BY CASE WHEN title = ? THEN 0 ELSE 1 END
            LIMIT 1""",
        [*instance_ids, layer, title, f"%{title}%", title],
    )
    return _row_to_node(rows[0]) if rows else None


def _row_to_node(row: dict, score: float = 0.0, match_type: str = "", keyword: str = "") -> dict:
    frontmatter = row["frontmatter"]
    if isinstance(frontmatter, str):
        frontmatter = json.loads(frontmatter)
    return {
        "instance_id": row["instance_id"],
        "path": row["file_path"],
        "title": row["title"],
        "score": score,
        "match_type": match_type,
        "match_keyword": keyword,
        "graph_layer": row["graph_layer"],
        "graph_role": row.get("graph_role"),
        "domain": row.get("domain"),
        "kind": row.get("kind"),
        "verification": row.get("verification", "unverified"),
        "frontmatter": frontmatter,
        "concepts": frontmatter.get("concepts", []),
    }


def _item_title(item: Any) -> str:
    if isinstance(item, str):
        return Path(item).stem if item.endswith(".md") else item
    if isinstance(item, dict):
        path = str(item.get("card") or item.get("path") or "")
        return str(item.get("title") or item.get("name") or Path(path).stem)
    return ""


def _item_path(item: Any) -> str:
    if isinstance(item, str) and item.endswith(".md"):
        return item
    if isinstance(item, dict):
        return str(item.get("card") or item.get("path") or item.get("source") or "")
    return ""


def _item_role(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("role") or "normal")
    return "normal"


def _role_score(role: str) -> float:
    return {"core": 1.0, "hub": 0.94, "primary": 1.0}.get(role, 0.88)


def _mark_map_node(note: dict, source_map: str, from_map_materials: bool = False) -> dict:
    note["map_sourced"] = True
    note["source_map"] = source_map
    if from_map_materials:
        note["from_map_materials"] = True
    return note


def _merge_unique(target: list[dict], additions: list[dict]) -> None:
    existing = {_node_key(item) for item in target}
    for item in additions:
        key = _node_key(item)
        if key not in existing:
            target.append(item)
            existing.add(key)
