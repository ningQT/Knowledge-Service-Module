"""Anchor positioning — 4-channel matching for anchor nodes.

Reference: 知识服务模块检索流程完整设计_v2 Section 9
"""

import json
import logging

from app.pipeline.search_models import AnchorCandidate
from app.pipeline.node_key import node_key as _node_key, row_key as _row_key
from app.storage.database import DatabaseBackend

logger = logging.getLogger(__name__)

# Anchor limits by intent type
ANCHOR_LIMITS = {
    "concept": 1,
    "topic_scan": 1,
    "compare": None,  # max(2, len(concept_candidates))
    "relation": 2,
    "source_trace": 1,
    "fallback": 5,
}


def locate_anchors(
    query_context: dict,
    db: DatabaseBackend,
) -> dict:
    """Locate anchor nodes using 4-channel matching.

    Returns dict with 'anchors' (list[dict]) and 'fallback_mode' (bool).
    """
    concept_candidates = query_context.get("concept_candidates", [])
    exact_candidates = query_context.get("exact_candidates") or concept_candidates
    phrase_candidates = query_context.get("phrase_candidates") or []
    expanded_candidates = query_context.get("expanded_candidates") or []
    domain_hint = query_context.get("domain_hint")
    intent_type = query_context.get("intent_type", "fallback")
    instance_ids = query_context.get("instance_ids", [])

    if not instance_ids or not (exact_candidates or phrase_candidates or expanded_candidates):
        return {"anchors": [], "fallback_mode": True}

    ch1 = _channel_title_exact(exact_candidates, instance_ids, db, candidate_layer="exact")
    ch2 = _channel_facets_exact(exact_candidates, instance_ids, db, candidate_layer="exact")
    ch3 = _channel_concepts_field(exact_candidates, instance_ids, db, candidate_layer="exact")
    ch4 = _channel_title_contains(phrase_candidates, instance_ids, db, candidate_layer="phrase")
    ch5 = _channel_source_fts(phrase_candidates, instance_ids, db, candidate_layer="phrase")
    ch6 = _channel_map_fts(phrase_candidates, instance_ids, db, candidate_layer="phrase")

    primary_channels = [ch1, ch2, ch3, ch4, ch5, ch6]
    merged = _merge_anchor_results(primary_channels)

    if not merged:
        fallback_candidates = expanded_candidates or phrase_candidates or exact_candidates
        merged = _fts_fallback(fallback_candidates, instance_ids, db, candidate_layer="expanded")
        if merged:
            return {"anchors": merged, "fallback_mode": True}
        return {"anchors": [], "fallback_mode": True}

    limit = ANCHOR_LIMITS.get(intent_type, 3)
    if limit is None:
        limit = max(2, len(concept_candidates))

    if expanded_candidates and len(merged) < limit:
        expanded_hits = _fts_fallback(expanded_candidates, instance_ids, db, candidate_layer="expanded")
        if expanded_hits:
            merged = _merge_anchor_results([merged, expanded_hits])

    final = merged[:limit]

    return {"anchors": final, "fallback_mode": False}


def _channel_title_exact(
    candidates: list[str],
    instance_ids: list[str],
    db: DatabaseBackend,
    candidate_layer: str = "exact",
) -> list[dict]:
    """Channel 1: title exact match (score 1.0)."""
    placeholders = ",".join("?" * len(instance_ids))
    lower_candidates = [c.lower() for c in candidates]

    results = []
    # 1a: Exact match (score=1.0)
    for batch_start in range(0, len(lower_candidates), 10):
        batch = lower_candidates[batch_start:batch_start + 10]
        clause_placeholders = ",".join("?" * len(batch))
        rows = db.execute(
            f"""SELECT instance_id, file_path, title, graph_layer, graph_role, domain, kind,
                       verification, frontmatter
                FROM notes
                WHERE instance_id IN ({placeholders})
                  AND LOWER(title) IN ({clause_placeholders})""",
            [*instance_ids, *batch],
        )
        for row in rows:
            fm = json.loads(row["frontmatter"]) if isinstance(row["frontmatter"], str) else row["frontmatter"]
            matched = next((c for c in candidates if c.lower() == row["title"].lower()), row["title"])
            results.append({
                "instance_id": row["instance_id"],
                "path": row["file_path"],
                "title": row["title"],
                "score": 1.0,
                "match_type": "title_exact",
                "match_keyword": matched,
                "candidate_layer": candidate_layer,
                "graph_layer": row["graph_layer"],
                "graph_role": row.get("graph_role"),
                "domain": row.get("domain"),
                "kind": row.get("kind"),
                "verification": row.get("verification", "unverified"),
                "frontmatter": fm,
            })
    return results


def _channel_title_contains(
    candidates: list[str],
    instance_ids: list[str],
    db: DatabaseBackend,
    candidate_layer: str = "phrase",
) -> list[dict]:
    """Channel: title substring match (score 0.78)."""
    if not candidates:
        return []
    placeholders = ",".join("?" * len(instance_ids))
    results = []
    seen_paths: set[str] = set()
    for candidate in candidates:
        if len(candidate) < 2:
            continue
        rows = db.execute(
            f"""SELECT instance_id, file_path, title, graph_layer, graph_role, domain, kind,
                       verification, frontmatter
                FROM notes
                WHERE instance_id IN ({placeholders})
                  AND title LIKE ?""",
            [*instance_ids, f"%{candidate}%"],
        )
        for row in rows:
            key = _row_key(row)
            if key not in seen_paths:
                fm = json.loads(row["frontmatter"]) if isinstance(row["frontmatter"], str) else row["frontmatter"]
                seen_paths.add(key)
                results.append({
                    "instance_id": row["instance_id"],
                    "path": row["file_path"],
                    "title": row["title"],
                    "score": 0.78,
                    "match_type": "title_contains",
                    "match_keyword": candidate,
                    "candidate_layer": candidate_layer,
                    "graph_layer": row["graph_layer"],
                    "graph_role": row.get("graph_role"),
                    "domain": row.get("domain"),
                    "kind": row.get("kind"),
                    "verification": row.get("verification", "unverified"),
                    "frontmatter": fm,
                })

    return results


def _channel_concepts_field(
    candidates: list[str],
    instance_ids: list[str],
    db: DatabaseBackend,
    candidate_layer: str = "exact",
) -> list[dict]:
    """Channel 2: concepts field match via json_each() (score 0.9)."""
    if not candidates:
        return []

    placeholders = ",".join("?" * len(instance_ids))
    candidate_ph = ",".join("?" * len(candidates))
    lower_candidates = [c.lower() for c in candidates]

    rows = db.execute(
        f"""SELECT DISTINCT n.instance_id, n.file_path, n.title, n.graph_layer, n.graph_role,
                    n.domain, n.kind, n.verification, n.frontmatter
            FROM notes n,
                 json_each(n.frontmatter, '$.concepts') AS je
            WHERE n.instance_id IN ({placeholders})
              AND LOWER(je.value) IN ({candidate_ph})""",
        [*instance_ids, *lower_candidates],
    )

    results = []
    for row in rows:
        fm = json.loads(row["frontmatter"]) if isinstance(row["frontmatter"], str) else row["frontmatter"]
        results.append({
            "instance_id": row["instance_id"],
            "path": row["file_path"],
            "title": row["title"],
            "score": 0.9,
            "match_type": "concepts_field",
            "candidate_layer": candidate_layer,
            "match_keyword": next(
                (c for c in candidates if c.lower() in [v.lower() for v in fm.get("concepts", [])]),
                candidates[0],
            ),
            "graph_layer": row["graph_layer"],
            "graph_role": row.get("graph_role"),
            "domain": row.get("domain"),
            "kind": row.get("kind"),
            "verification": row.get("verification", "unverified"),
            "frontmatter": fm,
        })
    return results


def _channel_source_fts(
    candidates: list[str],
    instance_ids: list[str],
    db: DatabaseBackend,
    candidate_layer: str = "phrase",
) -> list[dict]:
    """Channel 3: source FTS match for layer=1 (score 0.7)."""
    fts_query = _build_fts_query(candidates)
    if not fts_query:
        return []
    try:
        rows = db.fts_search(fts_query, instance_ids, layer=1, limit=5)
    except Exception:
        return []

    results = []
    for row in rows:
        fm = json.loads(row["frontmatter"]) if isinstance(row["frontmatter"], str) else row["frontmatter"]
        results.append({
            "instance_id": row.get("instance_id"),
            "path": row["file_path"],
            "title": row["title"],
            "score": 0.7,
            "match_type": "source_fts",
            "match_keyword": fts_query,
            "candidate_layer": candidate_layer,
            "graph_layer": row["graph_layer"],
            "graph_role": row.get("graph_role"),
            "domain": row.get("domain"),
            "kind": row.get("kind"),
            "verification": row.get("verification", "unverified"),
            "frontmatter": fm,
        })
    return results


def _channel_map_fts(
    candidates: list[str],
    instance_ids: list[str],
    db: DatabaseBackend,
    candidate_layer: str = "phrase",
) -> list[dict]:
    """Channel 4: map FTS match for layer=3 (score 0.6)."""
    fts_query = _build_fts_query(candidates)
    if not fts_query:
        return []
    try:
        rows = db.fts_search(fts_query, instance_ids, layer=3, limit=5)
    except Exception:
        return []

    results = []
    for row in rows:
        fm = json.loads(row["frontmatter"]) if isinstance(row["frontmatter"], str) else row["frontmatter"]
        results.append({
            "instance_id": row.get("instance_id"),
            "path": row["file_path"],
            "title": row["title"],
            "score": 0.6,
            "match_type": "map_fts",
            "match_keyword": fts_query,
            "candidate_layer": candidate_layer,
            "graph_layer": row["graph_layer"],
            "graph_role": row.get("graph_role"),
            "domain": row.get("domain"),
            "kind": row.get("kind"),
            "verification": row.get("verification", "unverified"),
            "frontmatter": fm,
        })
    return results


def _merge_anchor_results(channel_results: list[list[dict]]) -> list[dict]:
    """Merge channel results while preserving multi-channel match evidence."""
    best: dict[str, dict] = {}
    for channel in channel_results:
        for candidate in channel:
            path = _node_key(candidate)
            prepared = _with_match_metadata(candidate)
            if path not in best:
                best[path] = prepared
                continue
            existing = best[path]
            existing["matched_channels"] = _dedupe_values([
                *existing.get("matched_channels", []),
                *prepared.get("matched_channels", []),
            ])
            existing["candidate_layers"] = _dedupe_values([
                *existing.get("candidate_layers", []),
                *prepared.get("candidate_layers", []),
            ])
            existing["matched_keywords"] = _dedupe_values([
                *existing.get("matched_keywords", []),
                *prepared.get("matched_keywords", []),
            ])
            if prepared["score"] > existing["score"]:
                keep = {
                    "matched_channels": existing["matched_channels"],
                    "candidate_layers": existing["candidate_layers"],
                    "matched_keywords": existing["matched_keywords"],
                }
                existing.update(prepared)
                existing.update(keep)
            existing["base_score"] = max(
                float(existing.get("base_score", existing.get("score", 0.0))),
                float(prepared.get("base_score", prepared.get("score", 0.0))),
            )
            existing["synergy_score"] = _channel_synergy(existing)
    return sorted(best.values(), key=lambda x: x["score"], reverse=True)


def _with_match_metadata(candidate: dict) -> dict:
    prepared = dict(candidate)
    match_type = str(prepared.get("match_type") or "unknown")
    layer = str(prepared.get("candidate_layer") or "phrase")
    keyword = str(prepared.get("match_keyword") or "").strip()
    prepared["matched_channels"] = _dedupe_values([*prepared.get("matched_channels", []), match_type])
    prepared["candidate_layers"] = _dedupe_values([*prepared.get("candidate_layers", []), layer])
    prepared["matched_keywords"] = _dedupe_values([*prepared.get("matched_keywords", []), keyword])
    prepared["base_score"] = float(prepared.get("base_score", prepared.get("score", 0.0)))
    prepared["synergy_score"] = float(prepared.get("synergy_score", 0.0))
    return prepared


def _channel_synergy(candidate: dict) -> float:
    channels = candidate.get("matched_channels", [])
    layers = candidate.get("candidate_layers", [])
    if len(channels) <= 1:
        return 0.0
    weights = {"exact": 0.04, "phrase": 0.025, "expanded": 0.012}
    bonus = 0.0
    for layer in layers[1:]:
        bonus += weights.get(layer, 0.02)
    return min(bonus, 0.08)


def _dedupe_values(values: list) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _fts_fallback(
    candidates: list[str],
    instance_ids: list[str],
    db: DatabaseBackend,
    candidate_layer: str = "expanded",
) -> list[dict]:
    """FTS fallback when all 4 channels return nothing."""
    allow_short_cjk = candidate_layer == "expanded"
    fts_query = _build_fts_query(candidates, allow_short_cjk=allow_short_cjk)
    if not fts_query:
        return []
    try:
        rows = db.fts_search(fts_query, instance_ids, limit=5)
    except Exception:
        return []

    results = []
    for row in rows:
        fm = json.loads(row["frontmatter"]) if isinstance(row["frontmatter"], str) else row["frontmatter"]
        results.append({
            "instance_id": row.get("instance_id"),
            "path": row["file_path"],
            "title": row["title"],
            "score": 0.5,
            "match_type": "fts_fallback",
            "match_keyword": fts_query,
            "candidate_layer": candidate_layer,
            "graph_layer": row["graph_layer"],
            "graph_role": row.get("graph_role"),
            "domain": row.get("domain"),
            "kind": row.get("kind"),
            "verification": row.get("verification", "unverified"),
            "frontmatter": fm,
        })
    return results


def _channel_facets_exact(
    candidates: list[str],
    instance_ids: list[str],
    db: DatabaseBackend,
    candidate_layer: str = "exact",
) -> list[dict]:
    """Channel: normalized note_facets concepts/aliases exact match."""
    if not candidates:
        return []
    placeholders = ",".join("?" * len(instance_ids))
    candidate_ph = ",".join("?" * len(candidates))
    rows = db.execute(
        f"""SELECT DISTINCT n.instance_id, n.file_path, n.title, n.graph_layer, n.graph_role,
                   n.domain, n.kind, n.verification, n.frontmatter,
                   nf.field, nf.value
            FROM note_facets nf
            JOIN notes n
              ON n.instance_id = nf.instance_id
             AND n.file_path = nf.file_path
            WHERE nf.instance_id IN ({placeholders})
              AND nf.field IN ('aliases', 'concepts')
              AND lower(nf.value) IN ({candidate_ph})""",
        [*instance_ids, *[c.lower() for c in candidates]],
    )
    results = []
    for row in rows:
        fm = json.loads(row["frontmatter"]) if isinstance(row["frontmatter"], str) else row["frontmatter"]
        field = row.get("field")
        results.append({
            "instance_id": row["instance_id"],
            "path": row["file_path"],
            "title": row["title"],
            "score": 0.92 if field == "concepts" else 0.88,
            "match_type": f"{field}_facet_exact",
            "candidate_layer": candidate_layer,
            "match_keyword": row["value"],
            "graph_layer": row["graph_layer"],
            "graph_role": row.get("graph_role"),
            "domain": row.get("domain"),
            "kind": row.get("kind"),
            "verification": row.get("verification", "unverified"),
            "frontmatter": fm,
        })
    return results


def _build_fts_query(candidates: list[str], *, allow_short_cjk: bool = False) -> str:
    quoted: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = str(candidate or "").strip()
        if len(text) < 2:
            continue
        if not allow_short_cjk and _is_short_cjk_term(text):
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
