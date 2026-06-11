"""Candidate organization — assign to 4 groups + proactive refill.

Reference: 知识服务模块检索流程完整设计_v2 Section 11
"""

import json
import logging

from app.pipeline.node_key import node_key as _node_key, row_key as _row_key
from app.storage.database import DatabaseBackend

logger = logging.getLogger(__name__)


def organize_candidates(
    anchors: list[dict],
    expansion_result: dict,
) -> dict:
    """Assign anchor + expansion results to 4 groups.

    Returns dict with core_hits, related_cards, source_notes, maps.
    """
    anchor_paths = {_node_key(a) for a in anchors}
    core_hits = list(anchors)
    related_cards = []
    source_notes = []
    maps = []

    for path, node in expansion_result.get("nodes", {}).items():
        if _node_key(node) in anchor_paths:
            continue

        layer = node.get("graph_layer", 0)
        if layer == 2:
            related_cards.append(node)
        elif layer == 1:
            source_notes.append(node)
        elif layer == 3:
            maps.append(node)

    return {
        "core_hits": core_hits,
        "related_cards": related_cards,
        "source_notes": source_notes,
        "maps": maps,
    }


def proactive_refill(
    organized: dict,
    query_context: dict,
    db: DatabaseBackend,
) -> dict:
    """Proactively refill sparse groups via FTS and direct lookups."""
    phrase_candidates = query_context.get("phrase_candidates") or query_context.get("concept_candidates", [])
    expanded_candidates = query_context.get("expanded_candidates") or []
    refill_candidates = phrase_candidates or query_context.get("exact_candidates", [])
    domain = query_context.get("domain_hint")
    intent_type = query_context.get("intent_type", "fallback")
    instance_ids = query_context.get("instance_ids", [])

    existing_paths = (
        {_node_key(n) for n in organized["core_hits"]}
        | {_node_key(n) for n in organized["related_cards"]}
        | {_node_key(n) for n in organized["source_notes"]}
        | {_node_key(n) for n in organized["maps"]}
    )

    if len(organized["related_cards"]) < 3 and refill_candidates:
        _refill_related_cards(
            organized,
            existing_paths,
            refill_candidates,
            instance_ids,
            db,
            candidate_layer="phrase",
            score=0.45,
        )

    if len(organized["related_cards"]) < 3 and expanded_candidates:
        _refill_related_cards(
            organized,
            existing_paths,
            expanded_candidates,
            instance_ids,
            db,
            candidate_layer="expanded",
            score=0.30,
        )

    # Refill source_notes if empty — from core_hits frontmatter.sources
    if not organized["source_notes"]:
        for core in organized["core_hits"]:
            core_instance_id = core.get("instance_id")
            fm = core.get("frontmatter", {})
            if isinstance(fm, str):
                fm = json.loads(fm)
            for src_path in fm.get("sources", []):
                key = _node_key({"instance_id": core_instance_id, "path": src_path})
                if key in existing_paths:
                    continue
                info = _load_note_info(src_path, [core_instance_id] if core_instance_id else instance_ids, db)
                if info and info.get("graph_layer") == 1:
                    info["match_type"] = "source_trace_direct"
                    info["score"] = 0.9
                    organized["source_notes"].append(info)
                    existing_paths.add(_node_key(info))

    # Ontology supplement refill -- after FTS refill
    ontology_candidates = query_context.get("ontology_candidates")
    if ontology_candidates:
        _refill_from_ontology(organized, existing_paths, ontology_candidates)

    # Refill maps if empty and intent suggests maps are useful
    if not organized["maps"] and intent_type in ("topic_scan", "compare") and domain:
        try:
            rows = db.fts_search(domain, instance_ids, layer=3, limit=5)
            for row in rows:
                row_key = _row_key(row)
                if row_key in existing_paths:
                    continue
                fm = json.loads(row["frontmatter"]) if isinstance(row["frontmatter"], str) else row["frontmatter"]
                node = {
                    "path": row["file_path"],
                    "instance_id": row.get("instance_id"),
                    "title": row["title"],
                    "graph_layer": row["graph_layer"],
                    "graph_role": row.get("graph_role"),
                    "domain": row.get("domain"),
                    "kind": row.get("kind"),
                    "verification": row.get("verification", "unverified"),
                    "frontmatter": fm,
                    "concepts": fm.get("concepts", []),
                    "match_type": "fts_refill",
                    "candidate_layer": "phrase",
                    "score": 0.5,
                    "hop_distance": 1,
                    "rel_type_to_anchor": "fts_refill",
                }
                organized["maps"].append(node)
                existing_paths.add(_node_key(node))
        except Exception as e:
            logger.debug("FTS refill for maps failed: %s", e)

    return organized


def _refill_related_cards(
    organized: dict,
    existing_paths: set[str],
    candidates: list[str],
    instance_ids: list[str],
    db: DatabaseBackend,
    *,
    candidate_layer: str,
    score: float,
) -> None:
    fts_query = _build_fts_query(candidates)
    if not fts_query:
        return
    try:
        rows = db.fts_search(fts_query, instance_ids, layer=2, limit=10)
        for row in rows:
            if len(organized["related_cards"]) >= 3:
                break
            row_key = _row_key(row)
            if row_key in existing_paths:
                continue
            fm = json.loads(row["frontmatter"]) if isinstance(row["frontmatter"], str) else row["frontmatter"]
            node = {
                "path": row["file_path"],
                "instance_id": row.get("instance_id"),
                "title": row["title"],
                "graph_layer": row["graph_layer"],
                "graph_role": row.get("graph_role"),
                "domain": row.get("domain"),
                "kind": row.get("kind"),
                "verification": row.get("verification", "unverified"),
                "frontmatter": fm,
                "concepts": fm.get("concepts", []),
                "match_type": "fts_refill",
                "candidate_layer": candidate_layer,
                "candidate_layers": [candidate_layer],
                "matched_channels": ["fts_refill"],
                "base_score": score,
                "synergy_score": 0.0,
                "score": score,
                "hop_distance": 1,
                "rel_type_to_anchor": "fts_refill",
            }
            organized["related_cards"].append(node)
            existing_paths.add(_node_key(node))
    except Exception as e:
        logger.debug("FTS %s refill for related_cards failed: %s", candidate_layer, e)


def _load_note_info(file_path: str, instance_ids: list[str], db: DatabaseBackend) -> dict | None:
    """Load note info from the index."""
    placeholders = ",".join("?" * len(instance_ids))
    rows = db.execute(
        f"""SELECT instance_id, file_path, title, graph_layer, graph_role, domain, kind,
                   verification, frontmatter
            FROM notes
            WHERE file_path = ?
              AND instance_id IN ({placeholders})
            LIMIT 1""",
        [file_path, *instance_ids],
    )
    if not rows:
        return None
    row = rows[0]
    fm = json.loads(row["frontmatter"]) if isinstance(row["frontmatter"], str) else row["frontmatter"]
    return {
        "instance_id": row.get("instance_id"),
        "path": row["file_path"],
        "title": row["title"],
        "graph_layer": row["graph_layer"],
        "graph_role": row.get("graph_role"),
        "domain": row.get("domain"),
        "kind": row.get("kind"),
        "verification": row.get("verification", "unverified"),
        "frontmatter": fm,
        "concepts": fm.get("concepts", []),
    }


def _build_fts_query(candidates: list[str]) -> str:
    quoted: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = str(candidate or "").strip()
        if len(text) < 2:
            continue
        if _is_short_cjk_term(text):
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        quoted.append(f'"{text.replace(chr(34), chr(34) + chr(34))}"')
    return " OR ".join(quoted)


def _is_short_cjk_term(text: str) -> bool:
    cjk_chars = [char for char in text if "\u4e00" <= char <= "\u9fff"]
    return bool(cjk_chars) and len(cjk_chars) <= 3 and len(text.replace(" ", "")) <= 4


def _refill_from_ontology(
    organized: dict,
    existing_paths: set[str],
    ontology_candidates: list[dict],
) -> None:
    """Refill organized groups from ontology recall results."""
    for candidate in ontology_candidates:
        path = candidate.get("path")
        if not path or _node_key(candidate) in existing_paths:
            continue

        layer = candidate.get("graph_layer", 0)
        candidate["match_type"] = "ontology_recall"
        candidate["candidate_layer"] = "ontology"
        candidate["candidate_layers"] = ["ontology"]

        if layer == 2 and len(organized["related_cards"]) < 10:
            organized["related_cards"].append(candidate)
            existing_paths.add(_node_key(candidate))
        elif layer == 1 and len(organized["source_notes"]) < 5:
            organized["source_notes"].append(candidate)
            existing_paths.add(_node_key(candidate))
        elif layer == 3 and len(organized["maps"]) < 5:
            organized["maps"].append(candidate)
            existing_paths.add(_node_key(candidate))
