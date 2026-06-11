"""Search pipeline orchestrator — complete knowledge search flow.

Reference: 知识服务模块检索流程完整设计_v2 Section 13
"""

import logging
import time
from pathlib import Path

import yaml

from app.config import Settings, get_config_dir, get_settings
from app.pipeline.anchor_locator import locate_anchors
from app.pipeline.candidate_organizer import organize_candidates, proactive_refill
from app.pipeline.graph_expander import graph_expansion
from app.pipeline.map_priority import search_with_map_priority
from app.pipeline.ontology_adapter import OntologyAdapter
from app.pipeline.query_normalizer import normalize_query
from app.pipeline.query_parser import parse_query
from app.pipeline.query_router import route_query
from app.pipeline.ranker import rank_candidates
from app.pipeline.search_models import (
    ComprehensionResult,
    ConceptCoverage,
    DuplicatePair,
    HierarchyRelation,
    MapInsight,
    NodeStructure,
    SearchResult,
    SearchStats,
)
from app.shared_infra import (
    create_budget,
    decide_search_strategy,
    enforce_budget,
    extract_body,
    extract_key_sections,
    extract_structured_sections,
    extract_summary,
    parse_markdown_structure,
)
from app.shared_infra.models import ReadingStrategy
from app.shared_infra.truncation import truncate_with_marker
from app.storage.database import DatabaseBackend
from app.storage.filesystem import StorageBackend
from app.storage.path_utils import normalize_vault_path
from app.observability import log_event, query_hash

logger = logging.getLogger(__name__)

_strategy_cache: dict | None = None


def _load_strategy_params() -> dict:
    """Load strategy params from YAML. Cached after first load."""
    global _strategy_cache
    if _strategy_cache is not None:
        return _strategy_cache

    config_path = get_config_dir() / "strategy_params.yaml"

    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _strategy_cache = data.get("strategies", {})
    except Exception as e:
        logger.warning("Failed to load strategy params: %s, using defaults", e)
        _strategy_cache = {}
    return _strategy_cache


class SearchPipeline:
    """Orchestrates the complete search flow."""

    def __init__(
        self,
        db: DatabaseBackend,
        storage: StorageBackend | None = None,
        settings: Settings | None = None,
    ):
        self.db = db
        self.storage = storage
        self.settings = settings or get_settings()

    def search_knowledge(
        self,
        query: str,
        instance_ids: list[str] | None = None,
        layer_filter: int | None = None,
        verification_filter: str | None = None,
        include_comprehension: bool = True,
    ) -> SearchResult:
        """Execute the full search pipeline.

        Steps:
        1. Query normalization
        2. Query routing (intent classification)
        3. Query parsing (concept_candidates, domain_hint)
        4. Load strategy params
        5. Anchor positioning (4 channels)
        6. Graph expansion (BFS)
        7. Candidate organization (4 groups)
        7.5. Proactive refill
        8. Rule ranking
        9. Result trimming
        10. Assemble SearchResult
        """
        started = time.perf_counter()
        q_hash = query_hash(query)
        if not instance_ids:
            instance_ids = self._list_all_instances()
        log_event(
            logger,
            "search.pipeline.start",
            query_hash=q_hash,
            instance_ids=instance_ids,
            layer_filter=layer_filter,
            verification_filter=verification_filter,
            include_comprehension=include_comprehension,
        )

        try:
            # Step 1: Normalize
            normalized = normalize_query(query)

            # Step 2: Route
            intent_type = route_query(normalized, query)

            # Step 3: Parse
            query_context = parse_query(normalized, instance_ids, intent_type, self.db)
            log_event(
                logger,
                "search.intent.done",
                query_hash=q_hash,
                intent_type=intent_type,
                concept_count=len(query_context.get("concept_candidates", [])),
                domain_hint_present=bool(query_context.get("domain_hint")),
            )

            # Step 4: Strategy params
            strategies = _load_strategy_params()
            strategy = strategies.get(intent_type, strategies.get("fallback", {}))

            map_priority_enabled = bool(strategy.get("map_priority", False))
            if map_priority_enabled:
                map_priority_result = search_with_map_priority(
                    query_context=query_context,
                    intent_type=intent_type,
                    instance_ids=instance_ids,
                    max_depth=strategy.get("max_depth", 1),
                    db=self.db,
                )
                if map_priority_result:
                    ontology_adapter = OntologyAdapter(self.db)
                    ontology_candidates = ontology_adapter.recall_for_search(query_context, instance_ids)
                    if ontology_candidates:
                        query_context["ontology_candidates"] = ontology_candidates
                    organized = proactive_refill(
                        map_priority_result["organized"], query_context, self.db
                    )
                    if layer_filter is not None or verification_filter is not None:
                        organized = _filter_organized(
                            organized, layer_filter, verification_filter
                        )
                    log_event(
                        logger,
                        "search.graph_expand.done",
                        query_hash=q_hash,
                        search_path="map_priority",
                        key_relation_count=len(map_priority_result["key_relations"]),
                        **_organized_counts(organized),
                    )
                    return self._finalize_result(
                        query=query,
                        query_hash_value=q_hash,
                        pipeline_started=started,
                        intent_type=intent_type,
                        query_context=query_context,
                        organized=organized,
                        strategy=strategy,
                        fallback_mode=False,
                        search_path="map_priority",
                        map_priority=True,
                        key_relations=map_priority_result["key_relations"],
                        include_comprehension=include_comprehension,
                    )

            return self._search_card_scatter(
                query=query,
                query_hash_value=q_hash,
                pipeline_started=started,
                intent_type=intent_type,
                query_context=query_context,
                instance_ids=instance_ids,
                strategy=strategy,
                layer_filter=layer_filter,
                verification_filter=verification_filter,
                include_comprehension=include_comprehension,
            )
        except Exception:
            log_event(
                logger,
                "search.error",
                level=logging.ERROR,
                query_hash=q_hash,
                duration_ms=_duration_ms(started),
                exc_info=True,
            )
            raise

    def _search_card_scatter(
        self,
        query: str,
        query_hash_value: str,
        pipeline_started: float,
        intent_type: str,
        query_context: dict,
        instance_ids: list[str],
        strategy: dict,
        layer_filter: int | None,
        verification_filter: str | None,
        include_comprehension: bool = True,
    ) -> SearchResult:
        """Run the original v3 card-scatter search path."""
        # Step 3.5: Ontology recall (priority channel)
        ontology_adapter = OntologyAdapter(self.db)
        ontology_candidates = ontology_adapter.recall_for_search(query_context, instance_ids)
        if ontology_candidates:
            query_context["ontology_candidates"] = ontology_candidates
            log_event(
                logger,
                "search.ontology.recall",
                query_hash=query_hash_value,
                ontology_candidate_count=len(ontology_candidates),
            )

        # Step 5: Anchor positioning
        stage_started = time.perf_counter()
        anchor_result = locate_anchors(query_context, self.db)
        log_event(
            logger,
            "search.fts.done",
            query_hash=query_hash_value,
            anchor_count=len(anchor_result["anchors"]),
            fallback_mode=anchor_result["fallback_mode"],
            anchor_paths=_node_paths(anchor_result["anchors"]),
            match_types=_match_type_counts(anchor_result["anchors"]),
            duration_ms=_duration_ms(stage_started),
        )

        # Step 6: Graph expansion
        stage_started = time.perf_counter()
        max_depth = strategy.get("max_depth", 1)
        expansion_result = graph_expansion(
            anchors=anchor_result["anchors"],
            intent_type=intent_type,
            instance_ids=instance_ids,
            max_depth=max_depth,
            db=self.db,
        )
        log_event(
            logger,
            "search.graph_expand.done",
            query_hash=query_hash_value,
            search_path="card_scatter",
            total_nodes=expansion_result["stats"]["total_nodes"],
            total_edges=expansion_result["stats"]["total_edges"],
            max_depth_reached=expansion_result["stats"]["max_depth_reached"],
            duration_ms=_duration_ms(stage_started),
        )

        # Apply post-expansion filters
        if layer_filter is not None or verification_filter is not None:
            expansion_result["nodes"] = {
                k: v for k, v in expansion_result["nodes"].items()
                if _matches_filters(v, layer_filter, verification_filter)
            }
            anchor_result["anchors"] = [
                a for a in anchor_result["anchors"]
                if _matches_filters(a, layer_filter, verification_filter)
            ]

        # Step 7: Organize candidates
        organized = organize_candidates(
            anchors=anchor_result["anchors"],
            expansion_result=expansion_result,
        )

        # Step 7.5: Proactive refill
        organized = proactive_refill(organized, query_context, self.db)

        return self._finalize_result(
            query=query,
            query_hash_value=query_hash_value,
            pipeline_started=pipeline_started,
            intent_type=intent_type,
            query_context=query_context,
            organized=organized,
            strategy=strategy,
            fallback_mode=anchor_result["fallback_mode"],
            search_path="card_scatter",
            map_priority=False,
            key_relations=[],
            include_comprehension=include_comprehension,
        )

    def _finalize_result(
        self,
        query: str,
        query_hash_value: str,
        pipeline_started: float,
        intent_type: str,
        query_context: dict,
        organized: dict,
        strategy: dict,
        fallback_mode: bool,
        search_path: str,
        map_priority: bool,
        key_relations: list[dict],
        include_comprehension: bool = True,
    ) -> SearchResult:
        """Rank, trim, and assemble a SearchResult."""
        stage_started = time.perf_counter()
        ranked = rank_candidates(organized, query_context, self.db)

        # Step 9: Trim by result_limits
        result_limits = strategy.get("result_limits", {})
        for key, limit in result_limits.items():
            if key in ranked:
                ranked[key] = ranked[key][:limit]
        log_event(
            logger,
            "search.rank.done",
            query_hash=query_hash_value,
            duration_ms=_duration_ms(stage_started),
            **_organized_counts(ranked),
        )

        comprehension = (
            self._build_comprehension(
                query=query,
                intent_type=intent_type,
                query_context=query_context,
                ranked=ranked,
            )
            if include_comprehension
            else None
        )

        # Step 10: Assemble result
        stats = SearchStats(
            core_count=len(ranked["core_hits"]),
            related_count=len(ranked["related_cards"]),
            source_count=len(ranked["source_notes"]),
            map_count=len(ranked["maps"]),
            total=(len(ranked["core_hits"]) + len(ranked["related_cards"])
                   + len(ranked["source_notes"]) + len(ranked["maps"])),
            fallback_mode=fallback_mode,
            search_path=search_path,
            map_sourced_count=_count_map_sourced(ranked),
        )

        result = SearchResult(
            query=query,
            intent_type=intent_type,
            query_context={
                "concept_candidates": query_context["concept_candidates"],
                "exact_candidates": query_context.get("exact_candidates", []),
                "phrase_candidates": query_context.get("phrase_candidates", []),
                "expanded_candidates": query_context.get("expanded_candidates", []),
                "domain_hint": query_context["domain_hint"],
                "matched_facets": query_context.get("matched_facets", []),
            },
            core_hits=ranked["core_hits"],
            related_cards=ranked["related_cards"],
            source_notes=ranked["source_notes"],
            maps=ranked["maps"],
            map_priority=map_priority,
            key_relations=key_relations,
            stats=stats,
            comprehension=comprehension,
        )
        log_event(
            logger,
            "search.output",
            query_hash=query_hash_value,
            intent_type=result.intent_type,
            total=result.stats.total,
            core_count=result.stats.core_count,
            related_count=result.stats.related_count,
            source_count=result.stats.source_count,
            map_count=result.stats.map_count,
            fallback_mode=result.stats.fallback_mode,
            search_path=result.stats.search_path,
            core_paths=_node_paths(result.core_hits),
            map_paths=_node_paths(result.maps),
            duration_ms=_duration_ms(pipeline_started),
        )
        return result

    def _build_comprehension(
        self,
        query: str,
        intent_type: str,
        query_context: dict,
        ranked: dict,
    ) -> ComprehensionResult | None:
        """Build phase-two document reading comprehension for final search nodes."""
        if self.storage is None:
            return None
        try:
            nodes: list[NodeStructure] = []
            for group in ("core_hits", "related_cards", "source_notes", "maps"):
                for node in ranked.get(group, []):
                    nodes.append(self._scan_node_structure(node, group))

            keywords = query_context.get("concept_candidates") or [query]
            enriched = []
            for node in nodes:
                if node.missing or node.structure is None:
                    enriched.append(node)
                    continue
                node.strategy = decide_search_strategy(group=node.group, size_tier=node.structure.size_tier, intent_type=intent_type)
                node.content = self._read_node_content(node, keywords, intent_type)
                enriched.append(node)

            budget_limit = self._intent_budget(intent_type) - self._reserve_overhead(intent_type)
            budget = create_budget(max(2000, budget_limit))
            budget_items = [node.model_dump(mode="json") for node in enriched]
            priority = {"core_hits": 0, "maps": 1, "related_cards": 2, "source_notes": 3}
            budgeted, budget_status = enforce_budget(
                budget_items,
                budget,
                lambda item: len(item.get("content") or ""),
                priority,
                min_reserve=2000,
            )
            documents = [NodeStructure.model_validate(item) for item in budgeted]
            self._mark_primary_map(documents)

            concept_coverage = self._analyze_concept_coverage(
                documents, query_context.get("concept_candidates", [])
            )
            documents, budget_status, concept_coverage = self._compensate_intent_mismatch(
                enriched=documents,
                original_nodes=enriched,
                concept_coverage=concept_coverage,
                query_concepts=query_context.get("concept_candidates", []),
                keywords=keywords,
                intent_type=intent_type,
                budget_limit=max(2000, budget_limit),
                budget_status=budget_status,
            )
            duplicates = self._detect_duplicates(documents)
            hierarchy = self._build_hierarchy(documents)
            map_insights = self._extract_map_insights(documents)
            result = ComprehensionResult(
                documents=documents,
                concept_coverage=concept_coverage,
                duplicates=duplicates,
                hierarchy=hierarchy,
                map_insights=map_insights,
                budget_status=budget_status,
            )
            result.enhanced_prompt_context = self._build_enhanced_prompt_context(result)
            return result
        except Exception as exc:
            logger.warning("Search comprehension failed; returning v1 result shape: %s", exc)
            return None

    def _compensate_intent_mismatch(
        self,
        *,
        enriched: list[NodeStructure],
        original_nodes: list[NodeStructure],
        concept_coverage: ConceptCoverage,
        query_concepts: list[str],
        keywords: list[str],
        intent_type: str,
        budget_limit: int,
        budget_status,
    ) -> tuple[list[NodeStructure], object, ConceptCoverage]:
        """Re-read related cards when the first comprehension pass under-covers intent."""
        has_gaps = bool(concept_coverage.gap_concepts)
        low_coverage = concept_coverage.coverage_ratio < 0.30 and has_gaps
        under_used = budget_status.utilization < 0.30 and has_gaps
        if not (low_coverage or under_used):
            return enriched, budget_status, concept_coverage

        logger.info(
            "Compensating search comprehension: coverage=%.2f, budget=%.2f",
            concept_coverage.coverage_ratio,
            budget_status.utilization,
        )
        compensated: list[NodeStructure] = []
        expanded_keywords = list(dict.fromkeys([*keywords, *concept_coverage.gap_concepts]))
        for node in original_nodes:
            next_node = node.model_copy(deep=True)
            if next_node.group == "related_cards" and not next_node.missing and next_node.structure is not None:
                next_node.strategy = ReadingStrategy.KEY_SECTIONS
                next_node.content = self._read_node_content(next_node, expanded_keywords, intent_type)
            compensated.append(next_node)

        priority = {"core_hits": 0, "related_cards": 1, "maps": 2, "source_notes": 3}
        budgeted, compensated_status = enforce_budget(
            [node.model_dump(mode="json") for node in compensated],
            create_budget(budget_limit),
            lambda item: len(item.get("content") or ""),
            priority,
            min_reserve=2000,
        )
        documents = [NodeStructure.model_validate(item) for item in budgeted]
        self._mark_primary_map(documents)
        compensated_coverage = self._analyze_concept_coverage(documents, query_concepts)
        return documents, compensated_status, compensated_coverage

    def _scan_node_structure(self, node: dict, group: str) -> NodeStructure:
        path = normalize_vault_path(node.get("path") or node.get("file_path", ""))
        instance_id = node.get("instance_id")
        title = node.get("title") or Path(path).stem
        vault_path = self._get_vault_path(path, instance_id)
        if not vault_path:
            return NodeStructure(
                instance_id=instance_id,
                path=path,
                title=title,
                group=group,
                missing=True,
            )
        try:
            content = self.storage.read_file(str(Path(vault_path) / path))
            structure = parse_markdown_structure(content, mode="lite")
            return NodeStructure(
                instance_id=instance_id,
                path=path,
                title=title,
                group=group,
                note_type=node.get("type") or node.get("frontmatter", {}).get("type"),
                graph_layer=node.get("graph_layer", 0),
                graph_role=node.get("graph_role"),
                frontmatter=structure.frontmatter or node.get("frontmatter", {}),
                structure=structure,
            )
        except Exception as exc:
            logger.debug("Failed reading node %s: %s", path, exc)
            return NodeStructure(instance_id=instance_id, path=path, title=title, group=group, missing=True)

    def _read_node_content(
        self,
        node: NodeStructure,
        keywords: list[str],
        intent_type: str,
    ) -> str | None:
        if node.strategy == ReadingStrategy.SKIP:
            return None
        vault_path = self._get_vault_path(node.path, node.instance_id)
        if not vault_path or node.structure is None:
            return None
        content = self.storage.read_file(str(Path(vault_path) / node.path))
        if node.strategy == ReadingStrategy.FULL:
            return extract_body(content)
        if node.strategy == ReadingStrategy.KEY_SECTIONS:
            return extract_key_sections(content, node.structure, keywords, intent_type)
        if node.strategy == ReadingStrategy.SUMMARY:
            return extract_summary(content, node.structure)
        if node.strategy == ReadingStrategy.STRUCTURED_SECTIONS:
            return extract_structured_sections(content, node.structure)
        return None

    def _get_vault_path(self, file_path: str, instance_id: str | None = None) -> str | None:
        file_path = normalize_vault_path(file_path)
        if instance_id:
            rows = self.db.execute(
                """SELECT i.vault_path
                   FROM notes n
                   JOIN instances i ON n.instance_id = i.id
                   WHERE n.instance_id = ? AND n.file_path = ?
                   LIMIT 1""",
                (instance_id, file_path),
            )
            return rows[0]["vault_path"] if rows else None

        rows = self.db.execute(
            """SELECT i.vault_path
               FROM notes n
               JOIN instances i ON n.instance_id = i.id
               WHERE n.file_path = ?
               LIMIT 2""",
            (file_path,),
        )
        if not rows:
            return None
        if len(rows) > 1:
            logger.warning("Multiple vault paths found for file_path=%s; using first compatibility match", file_path)
        return rows[0]["vault_path"] if rows else None

    def _intent_budget(self, intent_type: str) -> int:
        return {
            "concept": 15000,
            "topic_scan": 30000,
            "compare": 25000,
            "relation": 20000,
            "source_trace": 10000,
            "fallback": 20000,
        }.get(intent_type, 20000)

    def _reserve_overhead(self, intent_type: str) -> int:
        overhead = {
            "concept": 1500,
            "topic_scan": 4500,
            "compare": 3000,
            "relation": 2000,
            "source_trace": 1000,
        }.get(intent_type, 1700)
        return overhead

    def _analyze_concept_coverage(
        self,
        documents: list[NodeStructure],
        query_concepts: list[str],
    ) -> ConceptCoverage:
        available = set()
        for doc in documents:
            for concept in doc.frontmatter.get("concepts", []) or []:
                available.add(str(concept))
        query_set = set(query_concepts)
        covered = sorted(query_set & available) if query_set else sorted(available)
        gaps = sorted(query_set - available)
        ratio = len(covered) / max(len(query_set), 1) if query_set else 1.0 if available else 0.0
        return ConceptCoverage(
            total_query_concepts=len(query_set),
            covered_concepts=covered,
            gap_concepts=gaps,
            coverage_ratio=ratio,
        )

    def _detect_duplicates(self, documents: list[NodeStructure]) -> list[DuplicatePair]:
        duplicates: list[DuplicatePair] = []
        for index, left in enumerate(documents):
            left_concepts = set(left.frontmatter.get("concepts", []) or [])
            if not left_concepts:
                continue
            for right in documents[index + 1:]:
                right_concepts = set(right.frontmatter.get("concepts", []) or [])
                union = left_concepts | right_concepts
                if not union:
                    continue
                overlap = left_concepts & right_concepts
                similarity = len(overlap) / len(union)
                if similarity > 0.5:
                    duplicates.append(
                        DuplicatePair(
                            node_a=left.path,
                            node_b=right.path,
                            similarity=similarity,
                            overlap_concepts=sorted(overlap),
                        )
                    )
        return duplicates

    def _build_hierarchy(self, documents: list[NodeStructure]) -> list[HierarchyRelation]:
        relations: list[HierarchyRelation] = []
        for doc in documents:
            role = doc.frontmatter.get("graph_role") or doc.graph_role or ""
            if role in {"core", "hub", "source"}:
                relations.append(
                    HierarchyRelation(parent=role, child=doc.path, relation_type="graph_role")
                )
            for source in doc.frontmatter.get("sources", []) or []:
                relations.append(
                    HierarchyRelation(parent=source, child=doc.path, relation_type="source_of")
                )
        return relations

    def _extract_map_insights(self, documents: list[NodeStructure]) -> list[MapInsight]:
        insights = []
        for doc in documents:
            if doc.group != "maps":
                continue
            insights.append(
                MapInsight(
                    source_map=doc.path,
                    map_title=doc.title,
                    is_primary=bool(doc.is_primary),
                    insight_preview=(doc.content or "")[:500],
                    core_concepts=doc.frontmatter.get("core_concepts", []) or [],
                    key_relations=doc.frontmatter.get("key_relations", []) or [],
                    reading_path=doc.frontmatter.get("reading_path", []) or [],
                )
            )
        return insights

    def _mark_primary_map(self, documents: list[NodeStructure]) -> None:
        maps = [doc for doc in documents if doc.group == "maps"]
        if not maps:
            return
        primary = max(maps, key=lambda doc: len(doc.frontmatter.get("concepts", []) or []))
        for doc in maps:
            doc.is_primary = doc.path == primary.path

    def _build_enhanced_prompt_context(self, comprehension: ComprehensionResult) -> str:
        sections = []
        if comprehension.concept_coverage:
            cc = comprehension.concept_coverage
            sections.append(f"## Covered concepts ({cc.coverage_ratio:.0%})")
            sections.append(", ".join(cc.covered_concepts) or "None")
            if cc.gap_concepts:
                sections.append("Gaps: " + ", ".join(cc.gap_concepts))
        if comprehension.hierarchy:
            sections.append("## Knowledge relations")
            for rel in comprehension.hierarchy[:10]:
                sections.append(f"- {rel.child} -> {rel.relation_type} -> {rel.parent}")
        if comprehension.map_insights:
            sections.append("## Map insights")
            for insight in comprehension.map_insights[:2]:
                sections.append(f"- {insight.map_title}: {insight.insight_preview}")
        if comprehension.duplicates:
            sections.append("## Duplicate warning")
            for dup in comprehension.duplicates[:5]:
                sections.append(f"- {dup.node_a} / {dup.node_b}: {dup.similarity:.2f}")
        result = "\n".join(sections)
        if comprehension.budget_status and len(result) > comprehension.budget_status.remaining:
            return truncate_with_marker(result, comprehension.budget_status.remaining)
        return result

    def _list_all_instances(self) -> list[str]:
        """List all instance IDs from the database."""
        rows = self.db.execute("SELECT id FROM instances")
        return [r["id"] for r in rows]


def _matches_filters(
    node,
    layer_filter: int | None,
    verification_filter: str | None,
) -> bool:
    """Check if a node matches the given layer and verification filters."""
    # Handle both dict and pydantic model access
    if hasattr(node, "graph_layer"):
        layer = node.graph_layer
        verification = node.verification
    else:
        layer = node.get("graph_layer", 0)
        verification = node.get("verification", "unverified")

    if layer_filter is not None and layer != layer_filter:
        return False
    if verification_filter is not None and verification != verification_filter:
        return False
    return True


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _node_paths(nodes: list[dict], limit: int = 5) -> list[str]:
    paths: list[str] = []
    for node in nodes[:limit]:
        path = node.get("path") or node.get("file_path") or node.get("id")
        if path:
            paths.append(str(path))
    return paths


def _match_type_counts(nodes: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in nodes:
        match_type = str(node.get("match_type") or "unknown")
        counts[match_type] = counts.get(match_type, 0) + 1
    return counts


def _organized_counts(organized: dict) -> dict[str, int]:
    return {
        "core_count": len(organized.get("core_hits", [])),
        "related_count": len(organized.get("related_cards", [])),
        "source_count": len(organized.get("source_notes", [])),
        "map_count": len(organized.get("maps", [])),
    }


def _count_map_sourced(ranked: dict) -> int:
    return sum(
        1
        for group in ("core_hits", "related_cards", "source_notes", "maps")
        for node in ranked.get(group, [])
        if node.get("map_sourced")
    )


def _filter_organized(
    organized: dict,
    layer_filter: int | None,
    verification_filter: str | None,
) -> dict:
    return {
        key: [
            node for node in organized.get(key, [])
            if _matches_filters(node, layer_filter, verification_filter)
        ]
        for key in ("core_hits", "related_cards", "source_notes", "maps")
    }
