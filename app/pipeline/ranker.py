"""Rule-based ranking for search candidates.

All weights are loaded from YAML config (configs/default.yaml), never hardcoded.
Reference: 知识服务模块检索流程完整设计_v2 Section 12
"""

import logging

import yaml

from app.config import get_config_dir
from app.pipeline.node_key import node_key as _node_key
from app.storage.database import DatabaseBackend

logger = logging.getLogger(__name__)

_config_cache: dict | None = None


def _load_ranking_config() -> dict:
    """Load ranking config from YAML. Cached after first load."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config_path = get_config_dir() / "default.yaml"

    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _config_cache = data.get("ranking", {})
    except Exception as e:
        logger.warning("Failed to load ranking config: %s, using empty config", e)
        _config_cache = {}
    return _config_cache


def rank_candidates(
    organized: dict,
    query_context: dict,
    db: DatabaseBackend,
) -> dict:
    """Rank each group using dedicated scoring factors."""
    config = _load_ranking_config()

    for node in organized["core_hits"]:
        node["score"] = _score_core_hit(node, config)
    organized["core_hits"].sort(key=lambda n: n["score"], reverse=True)

    for node in organized["related_cards"]:
        node["score"] = _score_related_card(node, query_context, config)
    organized["related_cards"].sort(key=lambda n: n["score"], reverse=True)

    # For source_notes: find which source paths are referenced by core/related
    core_source_paths = _get_source_paths_for_nodes(organized["core_hits"], db)
    related_source_paths = _get_source_paths_for_nodes(organized["related_cards"], db)
    for node in organized["source_notes"]:
        node["score"] = _score_source_note(
            node,
            core_source_paths,
            related_source_paths,
            query_context,
            config,
        )
    organized["source_notes"].sort(key=lambda n: n["score"], reverse=True)

    # For maps: coverage = how many core+related paths the map contains
    all_result_paths = (
        {_node_key(n) for n in organized["core_hits"]}
        | {_node_key(n) for n in organized["related_cards"]}
    )
    for node in organized["maps"]:
        node["score"] = _score_map(node, all_result_paths, query_context, db, config)
    organized["maps"].sort(key=lambda n: n["score"], reverse=True)

    return organized


def _score_core_hit(node: dict, config: dict) -> float:
    """Score core_hits: anchor_score * w1 + verification * w2."""
    weights = config.get("core_hits", {})
    aw = weights.get("anchor_score_weight", 0.8)
    vw = weights.get("verification_weight", 0.2)

    anchor_score = node.get("score", 0.5)
    verif_score = _verification_score(node.get("verification", "unverified"), config)
    score = anchor_score * aw + verif_score * vw + _map_priority_boost(node, config)
    return _finalize_score(score, node, config)


def _score_related_card(node: dict, query_context: dict, config: dict) -> float:
    """Score related_cards with 5 factors."""
    weights = config.get("related_cards", {})
    rw = weights.get("rel_type_weight", 0.35)
    dw = weights.get("distance_weight", 0.30)
    dmw = weights.get("domain_match_weight", 0.15)
    vw = weights.get("verification_weight", 0.10)
    cw = weights.get("concept_hit_weight", 0.10)

    rel_weight = _rel_type_weight(node.get("rel_type_to_anchor", "concept_overlap"), config)
    distance_score = _distance_penalty(node.get("hop_distance", 1), config)
    domain_score = 1.0 if node.get("domain") == query_context.get("domain_hint") else 0.3
    verif_score = _verification_score(node.get("verification", "unverified"), config)

    candidates = set(c.lower() for c in query_context.get("concept_candidates", []))
    node_concepts = set(c.lower() for c in node.get("concepts", []))
    overlap = len(candidates & node_concepts)
    concept_score = min(overlap / max(len(candidates), 1), 1.0)

    score = (rel_weight * rw + distance_score * dw + domain_score * dmw
             + verif_score * vw + concept_score * cw
             + _map_priority_boost(node, config))
    return _finalize_score(score, node, config)


def _score_source_note(
    node: dict,
    core_source_paths: set[str],
    related_source_paths: set[str],
    query_context: dict,
    config: dict,
) -> float:
    """Score source_notes with 4 factors."""
    weights = config.get("source_notes", {})
    cw = weights.get("referenced_by_core_weight", 0.40)
    rw = weights.get("referenced_by_related_weight", 0.25)
    dmw = weights.get("domain_match_weight", 0.15)
    vw = weights.get("verification_weight", 0.20)

    node_key = _node_key(node)
    core_ref = 1.0 if node_key in core_source_paths else 0.3
    related_ref = 1.0 if node_key in related_source_paths else 0.3
    domain_score = 1.0 if node.get("domain") == query_context.get("domain_hint") else 0.3
    verif_score = _verification_score(node.get("verification", "unverified"), config)

    score = (
        core_ref * cw
        + related_ref * rw
        + domain_score * dmw
        + verif_score * vw
        + _map_priority_boost(node, config)
    )
    return _finalize_score(score, node, config)


def _score_map(
    node: dict,
    covered_paths: set[str],
    query_context: dict,
    db: DatabaseBackend,
    config: dict,
) -> float:
    """Score maps with 4 factors."""
    weights = config.get("maps", {})
    covw = weights.get("coverage_weight", 0.40)
    dmw = weights.get("domain_match_weight", 0.30)
    vw = weights.get("verification_weight", 0.20)
    rw = weights.get("rel_type_weight", 0.10)

    # Coverage: how many covered_paths this map contains
    map_contains = _get_map_contained_cards(node["path"], node.get("instance_id"), db)
    coverage = len(set(map_contains) & covered_paths)
    max_coverage = max(len(covered_paths), 1)
    coverage_score = min(coverage / max_coverage, 1.0)

    domain_score = 1.0 if node.get("domain") == query_context.get("domain_hint") else 0.3
    verif_score = _verification_score(node.get("verification", "draft"), config)
    rel_weight = _rel_type_weight(node.get("rel_type_to_anchor", "concept_overlap"), config)

    score = (
        coverage_score * covw
        + domain_score * dmw
        + verif_score * vw
        + rel_weight * rw
        + _map_priority_boost(node, config)
    )
    return _finalize_score(score, node, config)


def _rel_type_weight(rel_type: str, config: dict) -> float:
    """Look up relation type weight from config."""
    weights = config.get("rel_type_weights", {})
    defaults = {
        "direct_link": 1.0,
        "source_trace": 1.0,
        "extracted_from": 0.9,
        "map_contains": 0.8,
        "concept_overlap": 0.6,
        "fts_fallback": 0.4,
        "fts_refill": 0.5,
    }
    return weights.get(rel_type, defaults.get(rel_type, 0.5))


def _apply_candidate_layer_cap(score: float, node: dict, config: dict) -> float:
    """Keep lower-confidence expanded hits from overtaking exact hits."""
    layer = _primary_candidate_layer(node)
    caps = config.get("candidate_layer_caps", {})
    defaults = {"exact": 1.0, "phrase": 0.82, "expanded": 0.58}
    cap = float(caps.get(layer, defaults.get(layer, 0.7)))
    return min(score, cap)


def _finalize_score(score: float, node: dict, config: dict) -> float:
    base_score = max(float(node.get("base_score", score)), score)
    synergy = _synergy_bonus(node, base_score, config)
    node["base_score"] = base_score
    node["synergy_score"] = synergy
    return _apply_candidate_layer_cap(base_score + synergy, node, config)


def _synergy_bonus(node: dict, base_score: float, config: dict) -> float:
    channels = node.get("matched_channels") or []
    if len(channels) <= 1:
        return float(node.get("synergy_score") or 0.0)

    synergy_config = config.get("candidate_synergy", {})
    layer_weights = synergy_config.get("layer_weights", {})
    defaults = {"exact": 0.035, "phrase": 0.025, "expanded": 0.012}
    layers = node.get("candidate_layers") or [node.get("candidate_layer") or "phrase"]
    bonus = 0.0
    for layer in layers[1:]:
        bonus += float(layer_weights.get(layer, defaults.get(layer, 0.02)))

    max_absolute = float(synergy_config.get("max_bonus", 0.08))
    max_ratio = float(synergy_config.get("max_base_ratio", 0.12))
    return min(bonus, max_absolute, base_score * max_ratio)


def _primary_candidate_layer(node: dict) -> str:
    priority = {"exact": 3, "phrase": 2, "expanded": 1}
    layers = node.get("candidate_layers") or [node.get("candidate_layer") or "phrase"]
    return max((str(layer) for layer in layers), key=lambda layer: priority.get(layer, 0))


def _distance_penalty(hop: int, config: dict) -> float:
    """Look up distance penalty from config."""
    penalties = config.get("distance_penalty", {})
    key = f"hop_{hop}"
    defaults = {1: 1.0, 2: 0.4}
    return penalties.get(key, defaults.get(hop, 0.2))


def _verification_score(verification: str, config: dict) -> float:
    """Look up verification score from config."""
    scores = config.get("verification_scores", {})
    defaults = {"verified": 1.0, "unverified": 0.5, "draft": 0.2}
    return scores.get(verification, defaults.get(verification, 0.2))


def _map_priority_boost(node: dict, config: dict) -> float:
    boosts = config.get("map_priority_boosts", {})
    score = 0.0
    if node.get("map_sourced"):
        score += boosts.get("map_sourced", 0.0)
    if node.get("is_primary"):
        score += boosts.get("primary_map", 0.0)
    if node.get("from_reading_path"):
        score += boosts.get("from_reading_path", 0.0)
    if node.get("from_map_materials"):
        score += boosts.get("from_map_materials", 0.0)
    role = node.get("map_role")
    if role:
        score += boosts.get("map_roles", {}).get(role, 0.0)
    return score


def _get_source_paths_for_nodes(nodes: list[dict], db: DatabaseBackend) -> set[str]:
    """Get source file paths referenced by nodes (via source_trace relations)."""
    if not nodes:
        return set()
    result: set[str] = set()
    for node in nodes:
        instance_id = node.get("instance_id")
        if not instance_id:
            continue
        rows = db.execute(
            """SELECT instance_id, target_path FROM relations
                WHERE instance_id = ? AND source_path = ? AND rel_type = 'source_trace'""",
            (instance_id, node["path"]),
        )
        result.update(_node_key({"instance_id": r["instance_id"], "path": r["target_path"]}) for r in rows)
    return result


def _get_map_contained_cards(map_path: str, instance_id: str | None, db: DatabaseBackend) -> list[str]:
    """Get card paths contained in a map (via map_contains relations)."""
    if not instance_id:
        return []
    rows = db.execute(
        """SELECT instance_id, target_path FROM relations
           WHERE instance_id = ? AND source_path = ? AND rel_type = 'map_contains'""",
        (instance_id, map_path),
    )
    return [_node_key({"instance_id": r["instance_id"], "path": r["target_path"]}) for r in rows]

