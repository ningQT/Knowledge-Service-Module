"""Instance-scoped ontology read-only query service for search recall."""

from __future__ import annotations

from typing import Any

from app.core.ontology_cache import (
    OntologyCacheData,
    get_ontology_cache,
)
from app.storage.database import DatabaseBackend

_AUTO_RECALL_CONFIDENCE = 0.6


class OntologyQueryService:
    """Read-only query service for ontology recall in search pipeline."""

    def __init__(self, db: DatabaseBackend):
        self.db = db

    def search_entities_by_name(
        self,
        instance_id: str,
        query_terms: list[str],
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search entities by name matching query terms."""
        if not query_terms:
            return []

        cache = get_ontology_cache(instance_id, self.db)
        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        for term in query_terms:
            term_norm = _norm_key(term)
            if not term_norm:
                continue

            for name_norm, entities in cache.entity_names.items():
                if term_norm in name_norm or name_norm in term_norm:
                    for entity in entities:
                        if entity.entity_id not in seen and self._entity_is_recallable(instance_id, entity):
                            seen.add(entity.entity_id)
                            results.append({
                                "entity_id": entity.entity_id,
                                "entity_name": entity.name,
                                "matched_channel": "name_match",
                                "confidence": entity.confidence,
                            })
                            if len(results) >= limit:
                                return results
        return results

    def search_entities_by_type_name(
        self,
        instance_id: str,
        type_names: list[str],
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search entities by their type name (type-to-instance recall)."""
        if not type_names:
            return []

        cache = get_ontology_cache(instance_id, self.db)
        matched_type_ids: set[str] = set()

        for type_name in type_names:
            type_norm = _norm_key(type_name)
            if not type_norm:
                continue
            for name_norm, types in cache.type_names.items():
                if type_norm in name_norm or name_norm in type_norm:
                    for t in types:
                        if self._type_is_recallable(t):
                            matched_type_ids.add(t.type_id)

        if not matched_type_ids:
            return []

        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for type_id in matched_type_ids:
            entity_ids = cache.type_to_entities.get(type_id, [])
            for entity_id in entity_ids:
                if entity_id in seen:
                    continue
                seen.add(entity_id)
                entity_info = self._find_entity_in_cache(cache, entity_id)
                if entity_info and self._entity_is_recallable(instance_id, entity_info):
                    results.append({
                        "entity_id": entity_id,
                        "entity_name": entity_info.name,
                        "matched_channel": "type_match",
                        "confidence": entity_info.confidence,
                    })
                    if len(results) >= limit:
                        return results
        return results

    def search_entities_by_alias(
        self,
        instance_id: str,
        query_terms: list[str],
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search entities by alias matching query terms."""
        if not query_terms:
            return []

        cache = get_ontology_cache(instance_id, self.db)
        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        for term in query_terms:
            term_norm = _norm_key(term)
            if not term_norm:
                continue
            for alias_norm, aliases in cache.entity_aliases.items():
                if term_norm in alias_norm or alias_norm in term_norm:
                    for alias_info in aliases:
                        if alias_info.entity_id not in seen:
                            entity_info = self._find_entity_in_cache(cache, alias_info.entity_id)
                            if entity_info and self._entity_is_recallable(instance_id, entity_info):
                                seen.add(alias_info.entity_id)
                                results.append({
                                    "entity_id": alias_info.entity_id,
                                    "entity_name": entity_info.name,
                                    "matched_channel": "alias_match",
                                    "matched_alias": alias_info.alias_text,
                                    "confidence": entity_info.confidence,
                                })
                                if len(results) >= limit:
                                    return results
        return results

    def get_related_entities(
        self,
        instance_id: str,
        entity_ids: list[str],
        *,
        relation_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get entities related to the given entity IDs via ontology relations."""
        if not entity_ids:
            return []

        sql = """SELECT r.id, r.source_entity_id, r.target_entity_id, r.relation_type,
                        r.description, r.confidence,
                        se.name AS source_name, te.name AS target_name
                 FROM ontology_relations r
                 JOIN ontology_entities se ON r.source_entity_id = se.id
                 JOIN ontology_entities te ON r.target_entity_id = te.id
                 WHERE r.instance_id = ? AND r.status = 'active' AND r.searchable = 1
                   AND (r.source_entity_id IN ({}) OR r.target_entity_id IN ({}))""".format(
            ",".join("?" * len(entity_ids)),
            ",".join("?" * len(entity_ids)),
        )
        params: list[Any] = [instance_id, *entity_ids, *entity_ids]

        if relation_types:
            placeholders = ",".join("?" * len(relation_types))
            sql += f" AND r.relation_type IN ({placeholders})"
            params.extend(relation_types)

        sql += " ORDER BY r.confidence DESC LIMIT ?"
        params.append(limit)

        rows = self.db.execute(sql, params)
        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        for row in rows:
            source_id = row["source_entity_id"]
            target_id = row["target_entity_id"]
            related_id = target_id if source_id in set(entity_ids) else source_id
            related_name = row["target_name"] if source_id in set(entity_ids) else row["source_name"]

            if related_id in seen:
                continue
            seen.add(related_id)
            results.append({
                "entity_id": related_id,
                "entity_name": related_name,
                "matched_channel": "relation_expand",
                "relation_type": row["relation_type"],
                "relation_description": row.get("description") or "",
                "confidence": float(row.get("confidence", 1.0)),
            })
        return results

    def get_entity_document_paths(
        self,
        instance_id: str,
        entity_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Get document paths linked to the given entities."""
        if not entity_ids:
            return []

        placeholders = ",".join("?" * len(entity_ids))
        rows = self.db.execute(
            """SELECT entity_id, file_path, link_type, snippet, confidence
               FROM ontology_entity_note_links
               WHERE instance_id = ? AND entity_id IN ({}) AND status = 'active'
               ORDER BY confidence DESC""".format(placeholders),
            [instance_id, *entity_ids],
        )
        return [
            {
                "entity_id": row["entity_id"],
                "file_path": row["file_path"],
                "link_type": row["link_type"],
                "snippet": row.get("snippet") or "",
                "confidence": float(row.get("confidence", 1.0)),
            }
            for row in rows
        ]

    def recall_for_query(
        self,
        instance_id: str,
        query_terms: list[str],
        *,
        intent_type: str = "fallback",
        domain_hint: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Combined recall: name + alias + type + relation, returning tagged results."""
        if not query_terms:
            return []

        entity_scores: dict[str, dict[str, Any]] = {}

        def _merge(entity_id: str, entity_name: str, channel: str, confidence: float, **extra: Any) -> None:
            if entity_id in entity_scores:
                entry = entity_scores[entity_id]
                if channel not in entry["matched_channels"]:
                    entry["matched_channels"].append(channel)
                entry["confidence"] = max(entry["confidence"], confidence)
            else:
                entity_scores[entity_id] = {
                    "entity_id": entity_id,
                    "entity_name": entity_name,
                    "matched_channels": [channel],
                    "confidence": confidence,
                    **extra,
                }

        # Channel 1: Name match
        for r in self.search_entities_by_name(instance_id, query_terms, limit=limit):
            _merge(r["entity_id"], r["entity_name"], "name_match", r["confidence"])

        # Channel 2: Alias match
        for r in self.search_entities_by_alias(instance_id, query_terms, limit=limit):
            _merge(r["entity_id"], r["entity_name"], "alias_match", r["confidence"],
                   matched_alias=r.get("matched_alias"))

        # Channel 3: Type match (for relation/intent queries)
        if intent_type in ("relation", "concept", "topic_scan", "compare"):
            for r in self.search_entities_by_type_name(instance_id, query_terms, limit=limit):
                _merge(r["entity_id"], r["entity_name"], "type_match", r["confidence"])

        # Channel 4: Relation expand (from already matched entities)
        matched_ids = list(entity_scores.keys())[:10]
        if matched_ids:
            for r in self.get_related_entities(instance_id, matched_ids, limit=limit):
                _merge(r["entity_id"], r["entity_name"], "relation_expand", r["confidence"],
                       relation_type=r.get("relation_type"))

        # Load bridge paths
        all_ids = list(entity_scores.keys())
        bridge_map: dict[str, list[dict[str, Any]]] = {}
        if all_ids:
            for link in self.get_entity_document_paths(instance_id, all_ids):
                eid = link["entity_id"]
                bridge_map.setdefault(eid, []).append({
                    "file_path": link["file_path"],
                    "link_type": link["link_type"],
                    "confidence": link["confidence"],
                })

        # Assemble results
        results: list[dict[str, Any]] = []
        for entity_id, info in entity_scores.items():
            bridges = bridge_map.get(entity_id, [])
            score = self._compute_recall_score(info["matched_channels"], info["confidence"])
            reason = self._build_recall_reason(info["matched_channels"])
            results.append({
                "entity_id": entity_id,
                "entity_name": info["entity_name"],
                "matched_channels": info["matched_channels"],
                "bridge_paths": bridges,
                "recall_score": score,
                "recall_reason": reason,
                "confidence": info["confidence"],
                "instance_id": instance_id,
            })

        results.sort(key=lambda x: x["recall_score"], reverse=True)
        return results[:limit]

    def _find_entity_in_cache(self, cache: OntologyCacheData, entity_id: str):
        """Find entity info in cache by ID."""
        for entities in cache.entity_names.values():
            for entity in entities:
                if entity.entity_id == entity_id:
                    return entity
        return None

    def _entity_is_recallable(self, instance_id: str, entity) -> bool:
        if entity.searchable and entity.status == "active":
            return True
        if entity.status != "candidate" or entity.confidence < _AUTO_RECALL_CONFIDENCE:
            return False
        rows = self.db.execute(
            """SELECT 1
               FROM ontology_entities e
               JOIN ontology_entity_note_links l
                 ON l.instance_id = e.instance_id
                AND l.entity_id = e.id
                AND l.status = 'active'
               WHERE e.instance_id = ? AND e.id = ? AND e.source = 'auto'
               LIMIT 1""",
            (instance_id, entity.entity_id),
        )
        return bool(rows)

    def _type_is_recallable(self, ontology_type) -> bool:
        return ontology_type.searchable and ontology_type.status == "active"

    def _compute_recall_score(self, channels: list[str], confidence: float) -> float:
        """Compute recall score based on matched channels."""
        channel_weights = {
            "name_match": 0.4,
            "alias_match": 0.3,
            "type_match": 0.2,
            "relation_expand": 0.15,
        }
        base = sum(channel_weights.get(ch, 0.1) for ch in channels)
        return min(1.0, base * confidence)

    def _build_recall_reason(self, channels: list[str]) -> str:
        """Build human-readable recall reason."""
        channel_labels = {
            "name_match": "名称匹配",
            "alias_match": "别名匹配",
            "type_match": "类型匹配",
            "relation_expand": "关系扩展",
        }
        labels = [channel_labels.get(ch, ch) for ch in channels]
        return "、".join(labels)


def _norm_key(value: str) -> str:
    return " ".join(str(value or "").strip().casefold().split())
