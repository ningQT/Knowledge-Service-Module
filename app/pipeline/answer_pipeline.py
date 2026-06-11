"""Map/card driven LLM answer synthesis pipeline."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable

from app.config import Settings, get_settings
from app.llm.client import LLMClient
from app.llm.parser import parse_llm_output
from app.llm.prompts.answer import (
    ANSWER_BATCH_SUMMARY_SYSTEM_PROMPT,
    ANSWER_BATCH_SUMMARY_USER_PROMPT,
    ANSWER_OVERVIEW_SYNTHESIS_SYSTEM_PROMPT,
    ANSWER_OVERVIEW_SYNTHESIS_USER_PROMPT,
    ANSWER_SECTION_SYNTHESIS_SYSTEM_PROMPT,
    ANSWER_SECTION_SYNTHESIS_USER_PROMPT,
    ANSWER_SYNTHESIS_USER_PROMPT,
    ANSWER_SYNTHESIS_RETRY_SYSTEM_PROMPT,
    ANSWER_SYNTHESIS_SYSTEM_PROMPT,
)
from app.pipeline.answer_models import (
    AnswerSection,
    AnswerResult,
    AnswerSynthesisOutput,
    BatchSummarizationOutput,
    BatchSummary,
    CardSummary,
    Citation,
    CoverageLedger,
    EvidenceCard,
    OverviewSynthesisOutput,
    ProcessSummary,
    SectionSynthesisOutput,
    TopicSummary,
)
from app.pipeline.search_models import SearchResult
from app.pipeline.search_pipeline import SearchPipeline
from app.schema.map_parser import structure_from_frontmatter
from app.schema.parser import parse_frontmatter
from app.shared_infra import extract_body
from app.shared_infra.truncation import truncate_with_marker
from app.storage.database import DatabaseBackend
from app.storage.filesystem import StorageBackend
from app.storage.path_utils import normalize_vault_path
from app.observability import log_event, query_hash

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, str, dict | None], None]

ANSWER_STEP_NAMES = {
    1: "question_understanding",
    2: "map_discovery",
    3: "card_reading",
    4: "citation_tracing",
    5: "batch_summarization",
    6: "answer_synthesis",
    7: "citation_validation",
}

ANSWER_BATCH_CARD_LIMIT = 5
ANSWER_BATCH_CARD_CONTENT_CHARS = 1800
ANSWER_TOPIC_SUMMARY_LIMIT = 8
ANSWER_SECTION_STATUS_VALUES = {"covered", "partial", "untraced"}
ANSWER_PARTIAL_CONTINUATION_HINT = "本次回答仍有部分相关卡片未进入最终合成，可在后续优化中继续总结剩余内容。"


class AnswerSynthesisPipeline:
    """Build an answer from maps and cards, citing source notes."""

    def __init__(
        self,
        db: DatabaseBackend,
        storage: StorageBackend,
        llm: LLMClient,
        settings: Settings | None = None,
    ):
        self.db = db
        self.storage = storage
        self.llm = llm
        self.settings = settings or get_settings()
        self._step_started: dict[int, float] = {}
        self._current_query_hash = ""

    def synthesize(
        self,
        query: str,
        instance_ids: list[str] | None = None,
        *,
        include_search_result: bool = False,
        include_comprehension: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> AnswerResult:
        """Generate an answer using map/card context and source-note citations."""
        self._step_started = {}
        self._current_query_hash = query_hash(query)
        if instance_ids == []:
            return AnswerResult(
                query=query,
                answer="",
                warnings=["No authorized knowledge bases are available."],
            )
        self._emit(progress_callback, 1, "running")
        search_result = SearchPipeline(self.db, self.storage, self.settings).search_knowledge(
            query=query,
            instance_ids=instance_ids,
            include_comprehension=include_comprehension,
        )
        self._emit(
            progress_callback,
            1,
            "completed",
            {
                "intent_type": search_result.intent_type,
                "concepts": search_result.query_context.get("concept_candidates", []),
            },
        )

        self._emit(progress_callback, 2, "running")
        context = self._build_knowledge_context(search_result, instance_ids)
        self._emit(
            progress_callback,
            2,
            "completed",
            {
                "maps": len(context["maps"]),
                "map_priority": search_result.map_priority,
                "key_relations": len(context["key_relations"]),
            },
        )

        self._emit(progress_callback, 3, "running")
        cards = context["cards"]
        self._emit(
            progress_callback,
            3,
            "completed",
            {
                "cards": len(cards),
                "cards_found": context["coverage_ledger"].cards_found,
                "cards_skipped_by_budget": context["coverage_ledger"].cards_skipped_by_budget,
                "card_titles": [card["title"] for card in cards[:5]],
            },
        )

        self._emit(progress_callback, 4, "running")
        evidence_cards, citations = self._trace_citations(cards, instance_ids)
        coverage_ledger = self._finalize_coverage_ledger(
            context["coverage_ledger"],
            citations,
        )
        self._emit(
            progress_callback,
            4,
            "completed",
            {
                "citations": len(citations),
                "traced": sum(1 for citation in citations if citation.traced),
                "untraced": sum(1 for citation in citations if not citation.traced),
            },
        )

        self._emit(progress_callback, 5, "running")
        batch_result = self._summarize_batches(query, cards, citations, progress_callback)
        batch_summaries = batch_result["batch_summaries"]
        batch_warnings = batch_result["warnings"]
        synthesis_batch_summaries = self._budget_batch_summaries(batch_summaries)
        topic_summaries = self._build_topic_summaries(
            synthesis_batch_summaries,
            cards,
            context["maps"],
        )
        coverage_ledger = self._finalize_summary_coverage_ledger(
            coverage_ledger,
            batch_summaries=batch_summaries,
            synthesis_batch_summaries=synthesis_batch_summaries,
            failed_batches=batch_result["failed_batches"],
        )
        context["coverage_ledger"] = coverage_ledger
        context["batch_summaries"] = synthesis_batch_summaries
        context["all_batch_summaries"] = batch_summaries
        context["topic_summaries"] = topic_summaries
        context["card_summaries"] = batch_result["card_summaries"]
        context["fallback_batch_ids"] = batch_result["fallback_batch_ids"]
        context["summary_batches_total"] = len(batch_summaries)
        for batch_detail in self._build_batch_summarization_details(
            context,
            coverage_ledger,
        )["batches"]:
            self._emit_thought(
                progress_callback,
                5,
                {
                    "type": "batch_detail",
                    "total_batches": len(batch_summaries),
                    "batch": batch_detail,
                },
            )
        self._emit(
            progress_callback,
            5,
            "completed",
            {
                "batches": len(batch_summaries),
                "used_batches": len(synthesis_batch_summaries),
                "failed_batches": batch_result["failed_batches"],
                "cards_summarized": coverage_ledger.cards_summarized,
            },
        )

        self._emit(progress_callback, 6, "running")
        synthesis_result = self._synthesize_sections_and_overview(
            query,
            context,
            citations,
            coverage_ledger,
            progress_callback,
        )
        llm_output = synthesis_result["llm_output"]
        sections = llm_output.sections
        synthesis_warnings = synthesis_result["warnings"]
        context["synthesis_stats"] = synthesis_result["stats"]
        process_summaries = self._build_process_summaries(
            search_result=search_result,
            context=context,
            coverage_ledger=coverage_ledger,
            evidence_cards=evidence_cards,
            citations=citations,
            llm_output=llm_output,
        )
        self._emit(
            progress_callback,
            6,
            "completed",
            {
                "key_points": len(llm_output.key_points),
                "answer_chars": len(llm_output.answer or ""),
                "answer_md_chars": len(llm_output.answer_md or ""),
            },
        )

        self._emit(progress_callback, 7, "running")
        warnings = [
            *context.get("read_warnings", []),
            *batch_warnings,
            *synthesis_warnings,
            *self._validate_citations(citations),
        ]
        self._emit(
            progress_callback,
            7,
            "completed",
            {
                "warnings": len(warnings),
                "untraced": sum(1 for citation in citations if not citation.traced),
            },
        )

        return AnswerResult(
            query=query,
            answer=llm_output.answer,
            answer_md=llm_output.answer_md,
            key_points=llm_output.key_points,
            citations=citations,
            evidence_cards=evidence_cards,
            process_summaries=process_summaries,
            coverage_ledger=coverage_ledger,
            batch_summaries=synthesis_batch_summaries,
            topic_summaries=topic_summaries,
            sections=sections,
            search_result=search_result.model_dump(mode="json") if include_search_result else None,
            comprehension=(
                search_result.comprehension.model_dump(mode="json")
                if include_comprehension and search_result.comprehension
                else None
            ),
            warnings=warnings,
        )

    def _build_knowledge_context(
        self,
        search_result: SearchResult,
        instance_ids: list[str] | None,
    ) -> dict[str, Any]:
        maps = []
        key_relations = list(search_result.key_relations or [])
        card_paths: list[str] = []
        card_map_paths: dict[str, list[str]] = {}

        for map_node in search_result.maps:
            fm = _as_frontmatter(map_node.get("frontmatter", {}))
            structure = structure_from_frontmatter(fm)
            map_info = {
                "path": map_node.get("path", ""),
                "title": map_node.get("title", ""),
                "core_concepts": structure.get("core_concepts", []),
                "reading_path": structure.get("reading_path", []),
                "key_relations": structure.get("key_relations", []),
                "source_materials": structure.get("source_materials", []),
            }
            maps.append(map_info)
            key_relations.extend(map_info["key_relations"])
            for item in [*map_info["core_concepts"], *map_info["reading_path"]]:
                path = _item_path(item)
                if not path:
                    continue
                _append_unique(card_paths, path)
                card_map_paths.setdefault(path, []).append(str(map_info["path"]))

        for group in (search_result.core_hits, search_result.related_cards):
            for node in group:
                if int(node.get("graph_layer") or 0) != 2:
                    continue
                path = str(node.get("path") or "")
                if path:
                    _append_unique(card_paths, path)

        cards = []
        read_warnings: list[str] = []
        for path in card_paths:
            note = self._load_note(path, instance_ids)
            if not note:
                continue
            if int(note["graph_layer"] or 0) != 2:
                continue
            try:
                content = self._read_note_body(note)
            except (OSError, UnicodeDecodeError) as exc:
                logger.warning(
                    "Skipping unreadable answer card %s: %s",
                    note["file_path"],
                    exc,
                )
                read_warnings.append(f"Skipped unreadable card: {note['file_path']}")
                continue
            cards.append(
                {
                    "path": note["file_path"],
                    "instance_id": note["instance_id"],
                    "title": note["title"],
                    "frontmatter": note["frontmatter"],
                    "content": content,
                    "map_paths": card_map_paths.get(note["file_path"], []),
                }
            )

        ledger = CoverageLedger(
            maps_found=len({str(item.get("path") or "") for item in maps if item.get("path")}),
            cards_found=len(card_paths),
            cards_read=len(cards),
        )
        return {
            "maps": maps,
            "cards": cards,
            "key_relations": key_relations[:30],
            "coverage_ledger": ledger,
            "read_warnings": read_warnings,
        }

    def _trace_citations(
        self,
        cards: list[dict],
        instance_ids: list[str] | None,
    ) -> tuple[list[EvidenceCard], list[Citation]]:
        source_to_cards: dict[str, list[str]] = {}
        evidence_cards: list[EvidenceCard] = []
        untraced_cards: list[str] = []

        for card in cards:
            card_path = card["path"]
            source_paths = self._source_paths_for_card(
                card_path,
                card.get("frontmatter", {}),
                card.get("instance_id"),
            )
            if source_paths:
                for source_path in source_paths:
                    source_to_cards.setdefault(source_path, []).append(card_path)
            else:
                untraced_cards.append(card_path)

            relation_chain = (
                ["knowledge_map", "knowledge_card", "source_note"]
                if card.get("map_paths")
                else ["knowledge_card", "source_note"]
            )
            if not source_paths:
                relation_chain = ["knowledge_card"]
            evidence_cards.append(
                EvidenceCard(
                    path=card_path,
                    title=card["title"],
                    source_note_paths=source_paths,
                    map_paths=card.get("map_paths", []),
                    relation_chain=relation_chain,
                    summary=truncate_with_marker(card.get("content") or "", 500),
                )
            )

        citations: list[Citation] = []
        for index, (source_path, card_paths) in enumerate(source_to_cards.items(), start=1):
            source_note = self._load_note(source_path, instance_ids)
            citations.append(
                Citation(
                    id=f"S{index}",
                    source_note_path=source_path,
                    source_title=_source_title(source_note, source_path),
                    evidence_cards=card_paths,
                    relation_chain=["knowledge_map", "knowledge_card", "source_note"],
                    traced=True,
                )
            )
        for card_path in untraced_cards:
            citations.append(
                Citation(
                    id=f"S{len(citations) + 1}",
                    source_note_path=None,
                    source_title="",
                    evidence_cards=[card_path],
                    relation_chain=["knowledge_card"],
                    traced=False,
                    note="No source note could be traced from this card.",
                )
            )
        return evidence_cards, citations

    def _summarize_batches(
        self,
        query: str,
        cards: list[dict],
        citations: list[Citation],
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        citation_ids_by_card = self._citation_ids_by_card(citations)
        card_summaries: list[CardSummary] = []
        batch_summaries: list[BatchSummary] = []
        warnings: list[str] = []
        failed_batches = 0
        fallback_batch_ids: list[str] = []
        total_batches = (len(cards) + ANSWER_BATCH_CARD_LIMIT - 1) // ANSWER_BATCH_CARD_LIMIT

        for index in range(0, len(cards), ANSWER_BATCH_CARD_LIMIT):
            batch = cards[index:index + ANSWER_BATCH_CARD_LIMIT]
            batch_id = f"B{len(batch_summaries) + 1}"
            self._emit_thought(
                progress_callback,
                5,
                {
                    "type": "batch_detail",
                    "total_batches": total_batches,
                    "batch": {
                        "batch_id": batch_id,
                        "status": "processing",
                        "card_count": len(batch),
                        "cards": self._batch_card_refs(batch),
                    },
                },
            )
            started = time.perf_counter()
            error: str | None = None
            metadata: dict[str, Any] = {}
            try:
                output, metadata = self._call_batch_summary_llm(
                    query,
                    batch_id,
                    batch,
                    citation_ids_by_card,
                )
                normalized = self._normalize_batch_summary_output(
                    output,
                    batch_id,
                    batch,
                    citation_ids_by_card,
                )
            except Exception as exc:
                error = str(exc)
                failed_batches += 1
                fallback_batch_ids.append(batch_id)
                logger.warning("Batch summary %s failed, using fallback: %s", batch_id, exc)
                warnings.append(f"Batch summary {batch_id} fell back to a rule-based summary.")
                normalized = self._fallback_batch_summary(batch_id, batch, citation_ids_by_card)

            card_summaries.extend(normalized.card_summaries)
            batch_summaries.append(normalized.batch_summary)
            self._emit_thought(
                progress_callback,
                5,
                {
                    "type": "batch_detail",
                    "total_batches": total_batches,
                    "batch": self._build_batch_process_detail(
                        normalized.batch_summary,
                        normalized.card_summaries,
                        status="completed",
                        fallback=batch_id in fallback_batch_ids,
                        error=error,
                        elapsed_ms=_duration_ms(started),
                        token_usage=metadata.get("token_usage"),
                        model=metadata.get("model"),
                    ),
                },
            )

        return {
            "card_summaries": card_summaries,
            "batch_summaries": batch_summaries,
            "failed_batches": failed_batches,
            "fallback_batch_ids": fallback_batch_ids,
            "warnings": warnings,
        }

    def _call_batch_summary_llm(
        self,
        query: str,
        batch_id: str,
        cards: list[dict],
        citation_ids_by_card: dict[str, list[str]],
    ) -> tuple[BatchSummarizationOutput, dict[str, Any]]:
        payload = {
            "query": query,
            "batch_id": batch_id,
            "cards": [
                {
                    "path": card["path"],
                    "title": card["title"],
                    "concepts": _as_list(card.get("frontmatter", {}).get("concepts"))[:8],
                    "graph_role": card.get("frontmatter", {}).get("graph_role", ""),
                    "map_paths": card.get("map_paths", []),
                    "allowed_citation_ids": citation_ids_by_card.get(card["path"], []),
                    "content": truncate_with_marker(
                        card.get("content") or "",
                        ANSWER_BATCH_CARD_CONTENT_CHARS,
                    ),
                }
                for card in cards
            ],
        }
        prompt = ANSWER_BATCH_SUMMARY_USER_PROMPT.format(
            payload=json.dumps(payload, ensure_ascii=False)
        )
        result = self.llm.chat_completion(
            [
                {
                    "role": "system",
                    "content": ANSWER_BATCH_SUMMARY_SYSTEM_PROMPT,
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=self.settings.llm_max_tokens,
            response_format={"type": "json_object"},
            call_name="answer.batch_summarization",
        )
        token_usage = (
            result.usage.model_dump(mode="json")
            if result.usage and result.usage.total_tokens > 0
            else None
        )
        return parse_llm_output(result.content, BatchSummarizationOutput), {
            "token_usage": token_usage,
            "model": result.model or self.settings.llm_model,
        }

    def _batch_card_refs(self, cards: list[dict]) -> list[dict[str, str]]:
        return [
            {
                "path": str(card.get("path") or ""),
                "title": str(card.get("title") or ""),
            }
            for card in cards
        ]

    def _build_batch_process_detail(
        self,
        batch_summary: BatchSummary,
        card_summaries: list[CardSummary],
        *,
        status: str,
        fallback: bool = False,
        error: str | None = None,
        elapsed_ms: int | None = None,
        token_usage: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        card_summary_by_path = {
            item.card_path: item
            for item in card_summaries
        }
        detail: dict[str, Any] = {
            "batch_id": batch_summary.batch_id,
            "status": status,
            "card_count": len(batch_summary.card_paths),
            "cards": [
                {
                    "path": card_path,
                    "title": card_summary.title if card_summary else "",
                    "citation_ids": card_summary.source_citation_ids if card_summary else [],
                    "key_points": card_summary.key_points if card_summary else [],
                }
                for card_path in batch_summary.card_paths
                for card_summary in [card_summary_by_path.get(card_path)]
            ],
            "summary": batch_summary.summary,
            "key_points": batch_summary.key_points,
            "citation_ids": batch_summary.citation_ids,
            "fallback": fallback,
        }
        if error:
            detail["error"] = error
        if elapsed_ms is not None:
            detail["elapsed_ms"] = elapsed_ms
        if token_usage:
            detail["token_usage"] = token_usage
        if model:
            detail["model"] = model
        return detail

    def _normalize_batch_summary_output(
        self,
        output: BatchSummarizationOutput,
        batch_id: str,
        cards: list[dict],
        citation_ids_by_card: dict[str, list[str]],
    ) -> BatchSummarizationOutput:
        card_by_path = {card["path"]: card for card in cards}
        summary_by_path = {
            normalize_vault_path(item.card_path): item
            for item in output.card_summaries
            if item.card_path
        }

        normalized_cards: list[CardSummary] = []
        for card_path, card in card_by_path.items():
            item = summary_by_path.get(card_path)
            if item is None:
                normalized_cards.append(
                    self._fallback_card_summary(card, citation_ids_by_card.get(card_path, []))
                )
                continue

            allowed_ids = citation_ids_by_card.get(card_path, [])
            citation_ids = _filter_allowed_ids(item.source_citation_ids, allowed_ids) or allowed_ids
            normalized_cards.append(
                CardSummary(
                    card_path=card_path,
                    title=item.title or card.get("title", ""),
                    relevance_to_query=truncate_with_marker(item.relevance_to_query, 300),
                    key_points=_limit_strings(item.key_points, 4, 300),
                    source_citation_ids=citation_ids,
                    conflicts_or_limits=_limit_strings(item.conflicts_or_limits, 4, 300),
                )
            )

        allowed_batch_ids = _unique(
            citation_id
            for card in normalized_cards
            for citation_id in card.source_citation_ids
        )
        batch_citation_ids = (
            _filter_allowed_ids(output.batch_summary.citation_ids, allowed_batch_ids)
            or allowed_batch_ids
        )
        batch_key_points = _limit_strings(output.batch_summary.key_points, 8, 300)
        if not batch_key_points:
            batch_key_points = _limit_strings(
                [
                    point
                    for card_summary in normalized_cards
                    for point in card_summary.key_points
                ],
                8,
                300,
            )
        batch_summary = BatchSummary(
            batch_id=batch_id,
            card_paths=list(card_by_path.keys()),
            summary=truncate_with_marker(
                output.batch_summary.summary or self._fallback_batch_text(cards),
                1600,
            ),
            key_points=batch_key_points,
            citation_ids=batch_citation_ids,
        )
        return BatchSummarizationOutput(
            card_summaries=normalized_cards,
            batch_summary=batch_summary,
        )

    def _fallback_batch_summary(
        self,
        batch_id: str,
        cards: list[dict],
        citation_ids_by_card: dict[str, list[str]],
    ) -> BatchSummarizationOutput:
        card_summaries = [
            self._fallback_card_summary(card, citation_ids_by_card.get(card["path"], []))
            for card in cards
        ]
        return BatchSummarizationOutput(
            card_summaries=card_summaries,
            batch_summary=BatchSummary(
                batch_id=batch_id,
                card_paths=[card["path"] for card in cards],
                summary=self._fallback_batch_text(cards),
                key_points=_limit_strings(
                    [
                        point
                        for card_summary in card_summaries
                        for point in card_summary.key_points
                    ],
                    8,
                    300,
                ),
                citation_ids=_unique(
                    citation_id
                    for card_summary in card_summaries
                    for citation_id in card_summary.source_citation_ids
                ),
            ),
        )

    def _fallback_card_summary(self, card: dict, citation_ids: list[str]) -> CardSummary:
        content = str(card.get("content") or "").strip()
        first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
        key_point = first_line or card.get("title", "")
        return CardSummary(
            card_path=card["path"],
            title=card.get("title", ""),
            relevance_to_query="规则兜底摘要：该卡片来自本次检索命中的知识上下文。",
            key_points=[truncate_with_marker(key_point, 300)] if key_point else [],
            source_citation_ids=citation_ids,
            conflicts_or_limits=["该卡片摘要由规则兜底生成，细节可能不如 LLM 摘要完整。"],
        )

    def _fallback_batch_text(self, cards: list[dict]) -> str:
        parts = []
        for card in cards:
            content = str(card.get("content") or "").strip()
            first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
            parts.append(f"{card.get('title', card['path'])}: {first_line}")
        return truncate_with_marker("\n".join(parts), 1600)

    def _citation_ids_by_card(self, citations: list[Citation]) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = {}
        for citation in citations:
            for card_path in citation.evidence_cards:
                _append_unique(mapping.setdefault(card_path, []), citation.id)
        return mapping

    def _budget_batch_summaries(
        self,
        batch_summaries: list[BatchSummary],
    ) -> list[BatchSummary]:
        limit = max(
            1200,
            min(
                self.settings.reading_budget_chars,
                int(self.settings.llm_context_window_chars * 0.6),
            ),
        )
        accepted: list[BatchSummary] = []
        used = 0
        for batch_summary in batch_summaries:
            estimate = len(json.dumps(batch_summary.model_dump(mode="json"), ensure_ascii=False))
            if used + estimate <= limit or not accepted:
                accepted.append(batch_summary)
                used += estimate
        return accepted

    def _build_topic_summaries(
        self,
        batch_summaries: list[BatchSummary],
        cards: list[dict],
        maps: list[dict],
    ) -> list[TopicSummary]:
        card_by_path = {card["path"]: card for card in cards}
        map_title_by_path = {
            str(item.get("path") or ""): str(item.get("title") or item.get("path") or "")
            for item in maps
        }
        grouped: dict[str, dict[str, Any]] = {}
        for batch_summary in batch_summaries:
            for card_path in batch_summary.card_paths:
                card = card_by_path.get(card_path)
                topic = self._topic_for_card(card, map_title_by_path)
                bucket = grouped.setdefault(
                    topic,
                    {
                        "batch_ids": [],
                        "card_paths": [],
                        "summary_parts": [],
                        "key_points": [],
                        "citation_ids": [],
                    },
                )
                _append_unique(bucket["batch_ids"], batch_summary.batch_id)
                _append_unique(bucket["card_paths"], card_path)
                bucket["summary_parts"].append(batch_summary.summary)
                for point in batch_summary.key_points:
                    if point not in bucket["key_points"]:
                        bucket["key_points"].append(point)
                for citation_id in batch_summary.citation_ids:
                    _append_unique(bucket["citation_ids"], citation_id)

        topic_summaries: list[TopicSummary] = []
        for topic, bucket in grouped.items():
            topic_summaries.append(
                TopicSummary(
                    topic=topic,
                    batch_ids=bucket["batch_ids"],
                    card_paths=bucket["card_paths"],
                    summary=truncate_with_marker("\n".join(bucket["summary_parts"]), 1600),
                    key_points=_limit_strings(bucket["key_points"], 10, 300),
                    citation_ids=bucket["citation_ids"],
                )
            )
        return topic_summaries[:ANSWER_TOPIC_SUMMARY_LIMIT]

    def _topic_for_card(
        self,
        card: dict | None,
        map_title_by_path: dict[str, str],
    ) -> str:
        if not card:
            return "Uncategorized"
        for map_path in card.get("map_paths", []):
            title = map_title_by_path.get(map_path)
            if title:
                return title
        frontmatter = card.get("frontmatter") or {}
        concepts = _as_list(frontmatter.get("concepts"))
        if concepts:
            return str(concepts[0])
        graph_role = frontmatter.get("graph_role")
        if graph_role:
            return str(graph_role)
        return "Uncategorized"

    def _synthesize_sections_and_overview(
        self,
        query: str,
        context: dict[str, Any],
        citations: list[Citation],
        coverage_ledger: CoverageLedger,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        citation_by_id = {citation.id: citation for citation in citations}
        topic_summaries = list(context.get("topic_summaries", []))
        sections: list[AnswerSection] = []
        warnings: list[str] = []
        section_successes = 0
        section_fallbacks = 0
        started = time.perf_counter()

        self._emit_thought(
            progress_callback,
            6,
            {
                "type": "synthesis_input",
                "used_batch_ids": [
                    item.batch_id for item in context.get("batch_summaries", [])
                ],
                "total_cards_summarized": coverage_ledger.cards_summarized,
                "citations_traced": coverage_ledger.citations_traced,
                "citations_untraced": coverage_ledger.citations_untraced,
                "topics": [
                    {
                        "topic": item.topic,
                        "batch_ids": item.batch_ids,
                        "card_paths": item.card_paths,
                        "citation_ids": item.citation_ids,
                    }
                    for item in topic_summaries
                ],
            },
        )

        if topic_summaries:
            for index, topic in enumerate(topic_summaries, start=1):
                try:
                    section = self._call_section_synthesis_llm(
                        query,
                        topic,
                        index,
                        context,
                        citations,
                        coverage_ledger,
                    )
                    normalized = self._normalize_answer_sections(
                        [section],
                        context,
                        citation_by_id,
                        coverage_ledger,
                    )
                    if not normalized:
                        raise ValueError("section synthesis returned no usable section")
                    sections.extend(normalized)
                    section_successes += 1
                except Exception as exc:
                    section_fallbacks += 1
                    logger.warning(
                        "Section synthesis for topic %s failed, using fallback: %s",
                        topic.topic,
                        exc,
                    )
                    warnings.append(
                        f"Section synthesis for topic {topic.topic or index} fell back to a rule-based summary."
                    )
                    sections.append(
                        self._fallback_section_from_topic(
                            topic,
                            index,
                            citation_by_id,
                        )
                    )
        else:
            fallback_sections = self._fallback_answer_sections(
                context,
                citation_by_id,
                coverage_ledger,
            )
            sections.extend(fallback_sections)
            section_fallbacks += len(fallback_sections)

        sections = self._mark_partial_sections(sections, coverage_ledger)
        overview_fallback = False
        try:
            overview = self._call_overview_synthesis_llm(
                query,
                sections,
                context,
                citations,
                coverage_ledger,
            )
            answer = truncate_with_marker(overview.answer.strip(), 5000)
            key_points = _limit_strings(overview.key_points, 8, 300)
            if not answer:
                raise ValueError("overview synthesis returned empty answer")
        except Exception as exc:
            overview_fallback = True
            logger.warning("Answer overview synthesis failed, using fallback: %s", exc)
            warnings.append("Answer overview synthesis fell back to a rule-based summary.")
            answer, key_points = self._fallback_overview_from_sections(sections)

        answer_md = self._compose_answer_markdown(
            answer=answer,
            key_points=key_points,
            sections=sections,
            citations=citations,
        )
        warnings.extend(self._validate_markdown_citations(answer_md, citations))
        stats = {
            "section_llm_success": section_successes,
            "section_fallbacks": section_fallbacks,
            "overview_fallback": overview_fallback,
            "warnings": len(warnings),
            "answer_md_chars": len(answer_md),
            "section_content_md_chars": sum(len(section.content_md or "") for section in sections),
        }
        llm_output = AnswerSynthesisOutput(
            answer=answer,
            answer_md=answer_md,
            key_points=key_points,
            sections=sections,
        )
        self._emit_thought(
            progress_callback,
            6,
            {
                "type": "synthesis_output",
                "section_titles": [section.title for section in sections],
                "section_count": len(sections),
                "key_points_count": len(key_points),
                "answer_chars": len(answer or ""),
                "answer_md_chars": len(answer_md),
                "section_content_md_chars": stats["section_content_md_chars"],
                "markdown_report": True,
                "section_llm_success": section_successes,
                "section_fallbacks": section_fallbacks,
                "overview_fallback": overview_fallback,
                "elapsed_ms": _duration_ms(started),
                "model": self.settings.llm_model,
            },
        )
        return {
            "llm_output": llm_output,
            "warnings": warnings,
            "stats": stats,
        }

    def _call_section_synthesis_llm(
        self,
        query: str,
        topic: TopicSummary,
        index: int,
        context: dict[str, Any],
        citations: list[Citation],
        coverage_ledger: CoverageLedger,
    ) -> AnswerSection:
        batch_by_id = {
            batch.batch_id: batch
            for batch in context.get("batch_summaries", [])
        }
        topic_batches = [
            batch_by_id[batch_id].model_dump(mode="json")
            for batch_id in topic.batch_ids
            if batch_id in batch_by_id
        ]
        allowed_citation_ids = _filter_allowed_ids(
            topic.citation_ids,
            [citation.id for citation in citations],
        )
        payload = {
            "query": query,
            "topic_index": index,
            "topic": topic.model_dump(mode="json"),
            "batch_summaries": topic_batches,
            "allowed_citation_ids": allowed_citation_ids,
            "allowed_batch_ids": topic.batch_ids,
            "allowed_card_paths": topic.card_paths,
            "coverage_ledger": coverage_ledger.model_dump(mode="json"),
        }
        prompt = ANSWER_SECTION_SYNTHESIS_USER_PROMPT.format(
            payload=json.dumps(payload, ensure_ascii=False)
        )
        result = self.llm.chat_completion(
            [
                {
                    "role": "system",
                    "content": ANSWER_SECTION_SYNTHESIS_SYSTEM_PROMPT,
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=self.settings.llm_max_tokens,
            response_format={"type": "json_object"},
            call_name="answer.section_synthesis",
        )
        if result.finish_reason == "length":
            compact_prompt = (
                "上一次输出被截断。请重新返回更紧凑的严格 JSON："
                "summary 控制在 1 句以内，content_md 控制在 1200 字以内，"
                "保留必要引用，不要输出额外解释。\n\n"
                f"{prompt}"
            )
            result = self.llm.chat_completion(
                [
                    {
                        "role": "system",
                        "content": ANSWER_SECTION_SYNTHESIS_SYSTEM_PROMPT,
                    },
                    {"role": "user", "content": compact_prompt},
                ],
                max_tokens=int(self.settings.llm_max_tokens * 1.5),
                response_format={"type": "json_object"},
                call_name="answer.section_synthesis_retry",
            )
        output = parse_llm_output(result.content, SectionSynthesisOutput)
        return output.section

    def _call_overview_synthesis_llm(
        self,
        query: str,
        sections: list[AnswerSection],
        context: dict[str, Any],
        citations: list[Citation],
        coverage_ledger: CoverageLedger,
    ) -> OverviewSynthesisOutput:
        payload = {
            "query": query,
            "sections": [
                {
                    "id": section.id,
                    "title": section.title,
                    "summary": section.summary,
                    "key_points": section.key_points,
                    "citations": section.citations,
                    "coverage_status": section.coverage_status,
                    "remaining_card_count": section.remaining_card_count,
                }
                for section in sections
            ],
            "coverage_ledger": coverage_ledger.model_dump(mode="json"),
            "citations": [
                {
                    "id": citation.id,
                    "source_title": citation.source_title,
                    "traced": citation.traced,
                }
                for citation in citations
            ],
            "summary_batches_used": len(context.get("batch_summaries", [])),
        }
        prompt = ANSWER_OVERVIEW_SYNTHESIS_USER_PROMPT.format(
            payload=json.dumps(payload, ensure_ascii=False)
        )
        result = self.llm.chat_completion(
            [
                {
                    "role": "system",
                    "content": ANSWER_OVERVIEW_SYNTHESIS_SYSTEM_PROMPT,
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=self.settings.llm_max_tokens,
            response_format={"type": "json_object"},
            call_name="answer.overview_synthesis",
        )
        return parse_llm_output(result.content, OverviewSynthesisOutput)

    def _fallback_section_from_topic(
        self,
        topic: TopicSummary,
        index: int,
        citation_by_id: dict[str, Citation],
    ) -> AnswerSection:
        citation_ids = _filter_allowed_ids(topic.citation_ids, list(citation_by_id.keys()))
        summary = truncate_with_marker(topic.summary, 1800)
        return AnswerSection(
            id=f"topic-{index}",
            title=topic.topic or f"Topic {index}",
            summary=summary,
            content_md=self._fallback_section_content_md(
                title=topic.topic or f"Topic {index}",
                summary=summary,
                key_points=topic.key_points,
                citation_ids=citation_ids,
            ),
            key_points=_limit_strings(topic.key_points, 8, 300),
            citations=citation_ids,
            batch_ids=topic.batch_ids,
            card_paths=topic.card_paths,
            coverage_status=self._section_coverage_status(
                citation_ids,
                citation_by_id,
            ),
            expandable=True,
        )

    def _fallback_overview_from_sections(
        self,
        sections: list[AnswerSection],
    ) -> tuple[str, list[str]]:
        if not sections:
            return "当前检索结果不足以生成完整知识整理答案。", []
        answer_parts = []
        key_points: list[str] = []
        for section in sections:
            if section.title or section.summary:
                answer_parts.append(
                    f"{section.title}: {section.summary}".strip()
                )
            for point in section.key_points:
                if point not in key_points:
                    key_points.append(point)
        answer = truncate_with_marker("\n\n".join(answer_parts), 5000)
        return answer, _limit_strings(key_points, 8, 300)

    def _call_synthesis_llm(
        self,
        query: str,
        context: dict[str, Any],
        evidence_cards: list[EvidenceCard],
        citations: list[Citation],
    ) -> AnswerSynthesisOutput:
        prompt = self._build_prompt(query, context, evidence_cards, citations)
        max_tokens = self.settings.llm_max_tokens
        result = self.llm.chat_completion(
            [
                {
                    "role": "system",
                    "content": ANSWER_SYNTHESIS_SYSTEM_PROMPT,
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            call_name="answer.synthesis",
        )
        if result.finish_reason == "length":
            retry = self.llm.chat_completion(
                [
                    {
                        "role": "system",
                        "content": ANSWER_SYNTHESIS_RETRY_SYSTEM_PROMPT,
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=int(max_tokens * 1.5),
                response_format={"type": "json_object"},
                call_name="answer.synthesis_retry",
            )
            result = retry
        return parse_llm_output(result.content, AnswerSynthesisOutput)

    def _build_prompt(
        self,
        query: str,
        context: dict[str, Any],
        evidence_cards: list[EvidenceCard],
        citations: list[Citation],
    ) -> str:
        evidence_payload = [
            {
                "path": card.path,
                "title": card.title,
                "source_note_paths": card.source_note_paths,
                "map_paths": card.map_paths,
                "relation_chain": card.relation_chain,
            }
            for card in evidence_cards
        ]
        payload = {
            "query": query,
            "maps": context["maps"],
            "key_relations": context["key_relations"],
            "batch_summaries": [
                item.model_dump(mode="json")
                for item in context.get("batch_summaries", [])
            ],
            "topic_summaries": [
                item.model_dump(mode="json")
                for item in context.get("topic_summaries", [])
            ],
            "coverage_ledger": context["coverage_ledger"].model_dump(mode="json"),
            "citations": [citation.model_dump(mode="json") for citation in citations],
            "evidence_cards": evidence_payload,
        }
        return ANSWER_SYNTHESIS_USER_PROMPT.format(
            payload=json.dumps(payload, ensure_ascii=False)
        )

    def _build_answer_sections(
        self,
        llm_output: AnswerSynthesisOutput,
        context: dict[str, Any],
        citations: list[Citation],
        coverage_ledger: CoverageLedger,
    ) -> list[AnswerSection]:
        citation_by_id = {citation.id: citation for citation in citations}
        sections = self._normalize_answer_sections(
            llm_output.sections,
            context,
            citation_by_id,
            coverage_ledger,
        )
        if not sections:
            sections = self._fallback_answer_sections(
                context,
                citation_by_id,
                coverage_ledger,
            )
        return self._mark_partial_sections(sections, coverage_ledger)

    def _normalize_answer_sections(
        self,
        sections: list[AnswerSection],
        context: dict[str, Any],
        citation_by_id: dict[str, Citation],
        coverage_ledger: CoverageLedger,
    ) -> list[AnswerSection]:
        valid_batch_ids = {item.batch_id for item in context.get("batch_summaries", [])}
        valid_card_paths = {
            card_path
            for item in context.get("batch_summaries", [])
            for card_path in item.card_paths
        }
        normalized: list[AnswerSection] = []
        for index, section in enumerate(sections, start=1):
            title = section.title.strip()
            summary = section.summary.strip()
            if not title and not summary:
                continue
            section_id = section.id.strip() or f"section-{index}"
            citations = _filter_allowed_ids(section.citations, list(citation_by_id.keys()))
            coverage_status = section.coverage_status
            if coverage_status not in ANSWER_SECTION_STATUS_VALUES:
                coverage_status = self._section_coverage_status(citations, citation_by_id)
            normalized.append(
                AnswerSection(
                    id=section_id,
                    title=title or f"Section {index}",
                    summary=truncate_with_marker(summary, 1800),
                    content_md=self._normalize_section_content_md(section),
                    key_points=_limit_strings(section.key_points, 8, 300),
                    citations=citations,
                    batch_ids=_filter_allowed_ids(section.batch_ids, list(valid_batch_ids)),
                    card_paths=_filter_allowed_ids(section.card_paths, list(valid_card_paths)),
                    coverage_status=coverage_status,
                    remaining_card_count=max(int(section.remaining_card_count or 0), 0),
                    expandable=bool(section.expandable),
                    continuation_hint=truncate_with_marker(section.continuation_hint, 300),
                )
            )
        if coverage_ledger.cards_skipped_by_budget == 0:
            for section in normalized:
                if section.coverage_status == "partial" and section.remaining_card_count == 0:
                    section.coverage_status = self._section_coverage_status(
                        section.citations,
                        citation_by_id,
                    )
        return normalized

    def _fallback_answer_sections(
        self,
        context: dict[str, Any],
        citation_by_id: dict[str, Citation],
        coverage_ledger: CoverageLedger,
    ) -> list[AnswerSection]:
        topic_summaries = context.get("topic_summaries", [])
        if topic_summaries:
            sections = []
            for index, topic in enumerate(topic_summaries, start=1):
                citation_ids = _filter_allowed_ids(topic.citation_ids, list(citation_by_id.keys()))
                summary = truncate_with_marker(topic.summary, 1800)
                sections.append(AnswerSection(
                    id=f"topic-{index}",
                    title=topic.topic or f"Topic {index}",
                    summary=summary,
                    content_md=self._fallback_section_content_md(
                        title=topic.topic or f"Topic {index}",
                        summary=summary,
                        key_points=topic.key_points,
                        citation_ids=citation_ids,
                    ),
                    key_points=_limit_strings(topic.key_points, 8, 300),
                    citations=citation_ids,
                    batch_ids=topic.batch_ids,
                    card_paths=topic.card_paths,
                    coverage_status=self._section_coverage_status(
                        topic.citation_ids,
                        citation_by_id,
                    ),
                    expandable=True,
                ))
            return sections

        batch_summaries = context.get("batch_summaries", [])
        if batch_summaries:
            citation_ids = _unique(
                citation_id
                for batch in batch_summaries
                for citation_id in batch.citation_ids
            )
            card_paths = _unique(
                card_path
                for batch in batch_summaries
                for card_path in batch.card_paths
            )
            summary = truncate_with_marker(
                "\n".join(batch.summary for batch in batch_summaries),
                1800,
            )
            key_points = _limit_strings(
                [
                    point
                    for batch in batch_summaries
                    for point in batch.key_points
                ],
                8,
                300,
            )
            return [
                AnswerSection(
                    id="summary-batches",
                    title="Structured knowledge summary",
                    summary=summary,
                    content_md=self._fallback_section_content_md(
                        title="Structured knowledge summary",
                        summary=summary,
                        key_points=key_points,
                        citation_ids=_filter_allowed_ids(citation_ids, list(citation_by_id.keys())),
                    ),
                    key_points=key_points,
                    citations=_filter_allowed_ids(citation_ids, list(citation_by_id.keys())),
                    batch_ids=[batch.batch_id for batch in batch_summaries],
                    card_paths=card_paths,
                    coverage_status="covered" if coverage_ledger.cards_skipped_by_budget == 0 else "partial",
                    expandable=True,
                )
            ]
        return []

    def _normalize_section_content_md(self, section: AnswerSection) -> str:
        content = (section.content_md or "").strip()
        if content:
            return truncate_with_marker(content, 6000)
        return self._fallback_section_content_md(
            title=section.title,
            summary=section.summary,
            key_points=section.key_points,
            citation_ids=section.citations,
        )

    def _fallback_section_content_md(
        self,
        *,
        title: str,
        summary: str,
        key_points: list[str],
        citation_ids: list[str],
    ) -> str:
        parts: list[str] = []
        if summary:
            parts.append(truncate_with_marker(summary.strip(), 1800))
        limited_points = _limit_strings(key_points, 8, 300)
        if limited_points:
            parts.append("### 关键要点")
            parts.extend(f"- {point}" for point in limited_points)
        if citation_ids:
            parts.append(f"引用来源：{', '.join(f'[{citation_id}]' for citation_id in citation_ids)}")
        if not parts:
            parts.append(f"{title or '该主题'} 暂无可展开的详细摘要。")
        return "\n\n".join(parts)

    def _compose_answer_markdown(
        self,
        *,
        answer: str,
        key_points: list[str],
        sections: list[AnswerSection],
        citations: list[Citation],
    ) -> str:
        parts: list[str] = []
        limited_points = _limit_strings(key_points, 8, 300)
        if limited_points:
            parts.append("> **核心要点**")
            parts.extend(f"> - {point}" for point in limited_points)
            parts.append("")

        if answer.strip():
            parts.append("## 总览")
            parts.append(answer.strip())

        for index, section in enumerate(sections, start=1):
            title = section.title or f"主题 {index}"
            parts.append(f"## {_section_ordinal(index)}、{title}")
            content_md = (section.content_md or "").strip()
            if not content_md:
                content_md = self._fallback_section_content_md(
                    title=title,
                    summary=section.summary,
                    key_points=section.key_points,
                    citation_ids=section.citations,
                )
            parts.append(content_md)

        if citations:
            parts.append("## 参考来源")
            for citation in citations:
                source_title = citation.source_title or citation.source_note_path or "未追溯来源"
                line = f"- [{citation.id}] {source_title}"
                if citation.source_note_path:
                    line += f"  \n  `{citation.source_note_path}`"
                if not citation.traced:
                    line += "  \n  未完全追溯到 source note"
                parts.append(line)

        return "\n\n".join(part for part in parts if part).strip()

    def _validate_markdown_citations(
        self,
        markdown_text: str,
        citations: list[Citation],
    ) -> list[str]:
        valid_ids = {citation.id for citation in citations}
        referenced_ids = set(re.findall(r"\[(S\d+)\]", markdown_text or ""))
        invalid_ids = sorted(referenced_ids - valid_ids)
        if not invalid_ids:
            return []
        return [
            "Markdown answer references non-existent citation(s): "
            + ", ".join(invalid_ids)
        ]

    def _mark_partial_sections(
        self,
        sections: list[AnswerSection],
        coverage_ledger: CoverageLedger,
    ) -> list[AnswerSection]:
        if not sections or coverage_ledger.cards_skipped_by_budget <= 0:
            return sections
        target = sections[0]
        target.coverage_status = "partial"
        target.remaining_card_count = max(
            target.remaining_card_count,
            coverage_ledger.cards_skipped_by_budget,
        )
        if not target.continuation_hint:
            target.continuation_hint = ANSWER_PARTIAL_CONTINUATION_HINT
        return sections

    def _section_coverage_status(
        self,
        citation_ids: list[str],
        citation_by_id: dict[str, Citation],
    ) -> str:
        citations = [citation_by_id[citation_id] for citation_id in citation_ids if citation_id in citation_by_id]
        if citations and all(not citation.traced for citation in citations):
            return "untraced"
        return "covered"

    def _finalize_coverage_ledger(
        self,
        ledger: CoverageLedger,
        citations: list[Citation],
    ) -> CoverageLedger:
        return ledger.model_copy(
            update={
                "citations_total": len(citations),
                "citations_traced": sum(1 for citation in citations if citation.traced),
                "citations_untraced": sum(1 for citation in citations if not citation.traced),
            }
        )

    def _finalize_summary_coverage_ledger(
        self,
        ledger: CoverageLedger,
        *,
        batch_summaries: list[BatchSummary],
        synthesis_batch_summaries: list[BatchSummary],
        failed_batches: int,
    ) -> CoverageLedger:
        summarized_cards = _unique(
            card_path
            for batch_summary in batch_summaries
            for card_path in batch_summary.card_paths
        )
        synthesis_cards = _unique(
            card_path
            for batch_summary in synthesis_batch_summaries
            for card_path in batch_summary.card_paths
        )
        return ledger.model_copy(
            update={
                "cards_summarized": len(summarized_cards),
                "cards_used_for_synthesis": len(synthesis_cards),
                "cards_skipped_by_budget": max(ledger.cards_read - len(synthesis_cards), 0),
                "summary_batches_total": len(batch_summaries),
                "summary_batches_used": len(synthesis_batch_summaries),
                "summary_batches_failed": failed_batches,
            }
        )

    def _build_process_summaries(
        self,
        *,
        search_result: SearchResult,
        context: dict[str, Any],
        coverage_ledger: CoverageLedger,
        evidence_cards: list[EvidenceCard],
        citations: list[Citation],
        llm_output: AnswerSynthesisOutput,
    ) -> list[ProcessSummary]:
        batch_summary_details = self._build_batch_summarization_details(
            context,
            coverage_ledger,
        )
        synthesis_details = self._build_answer_synthesis_details(
            context=context,
            coverage_ledger=coverage_ledger,
            citations=citations,
            llm_output=llm_output,
        )
        summaries = [
            ProcessSummary(
                step="batch_summarization",
                title="Batch summarization",
                summary=(
                    f"Generated {coverage_ledger.summary_batches_total} summary batch(es); "
                    f"used {coverage_ledger.summary_batches_used}; "
                    f"fallback {coverage_ledger.summary_batches_failed}."
                ),
                details=batch_summary_details,
            ),
            ProcessSummary(
                step="answer_synthesis",
                title="Answer synthesis",
                summary=(
                    f"Synthesized {len(llm_output.key_points)} key point(s), "
                    f"{len(llm_output.sections)} section(s), "
                    f"and {len(citations)} citation(s)."
                ),
                details=synthesis_details,
            ),
        ]
        llm_notes = []
        for item in llm_output.process_summaries:
            if not isinstance(item, dict):
                continue
            llm_notes.append(
                {
                    "step": str(item.get("step") or "answer_synthesis"),
                    "title": str(item.get("title") or "Answer synthesis"),
                    "summary": str(item.get("summary") or ""),
                    "details": item.get("details") if isinstance(item.get("details"), dict) else {},
                }
            )
        if llm_notes:
            summaries[1].details["llm_notes"] = llm_notes
        return summaries

    def _build_batch_summarization_details(
        self,
        context: dict[str, Any],
        coverage_ledger: CoverageLedger,
    ) -> dict[str, Any]:
        card_title_by_path = {
            card.get("path", ""): card.get("title", "")
            for card in context.get("cards", [])
        }
        card_summary_by_path = {
            item.card_path: item
            for item in context.get("card_summaries", [])
        }
        used_batch_ids = {
            item.batch_id
            for item in context.get("batch_summaries", [])
        }
        fallback_batch_ids = set(context.get("fallback_batch_ids", []))
        batches = []
        for batch_summary in context.get("all_batch_summaries", context.get("batch_summaries", [])):
            cards = []
            for card_path in batch_summary.card_paths:
                card_summary = card_summary_by_path.get(card_path)
                cards.append(
                    {
                        "path": card_path,
                        "title": (
                            card_summary.title
                            if card_summary and card_summary.title
                            else card_title_by_path.get(card_path, "")
                        ),
                        "citation_ids": (
                            card_summary.source_citation_ids
                            if card_summary
                            else []
                        ),
                        "key_points": (
                            card_summary.key_points
                            if card_summary
                            else []
                        ),
                    }
                )
            batches.append(
                {
                    "batch_id": batch_summary.batch_id,
                    "status": "completed",
                    "card_count": len(batch_summary.card_paths),
                    "cards": cards,
                    "summary": batch_summary.summary,
                    "key_points": batch_summary.key_points,
                    "citation_ids": batch_summary.citation_ids,
                    "fallback": batch_summary.batch_id in fallback_batch_ids,
                    "used_for_synthesis": batch_summary.batch_id in used_batch_ids,
                }
            )
        return {
            "cards_summarized": coverage_ledger.cards_summarized,
            "summary_batches_total": coverage_ledger.summary_batches_total,
            "summary_batches_used": coverage_ledger.summary_batches_used,
            "summary_batches_failed": coverage_ledger.summary_batches_failed,
            "fallback_batch_ids": list(fallback_batch_ids),
            "batches": batches,
        }

    def _build_answer_synthesis_details(
        self,
        *,
        context: dict[str, Any],
        coverage_ledger: CoverageLedger,
        citations: list[Citation],
        llm_output: AnswerSynthesisOutput,
    ) -> dict[str, Any]:
        topic_summaries = context.get("topic_summaries", [])
        synthesis_stats = context.get("synthesis_stats", {})
        return {
            "used_batch_ids": [
                item.batch_id for item in context.get("batch_summaries", [])
            ],
            "topic_count": len(topic_summaries),
            "topics": [
                {
                    "topic": item.topic,
                    "batch_ids": item.batch_ids,
                    "card_paths": item.card_paths,
                    "citation_ids": item.citation_ids,
                }
                for item in topic_summaries
            ],
            "citation_count": len(citations),
            "citations_traced": coverage_ledger.citations_traced,
            "citations_untraced": coverage_ledger.citations_untraced,
            "section_count": len(llm_output.sections),
            "section_titles": [section.title for section in llm_output.sections],
            "key_points_count": len(llm_output.key_points),
            "answer_chars": len(llm_output.answer or ""),
            "answer_md_chars": len(llm_output.answer_md or ""),
            "section_content_md_chars": sum(
                len(section.content_md or "")
                for section in llm_output.sections
            ),
            "markdown_report": bool(llm_output.answer_md),
            "section_llm_success": int(synthesis_stats.get("section_llm_success", 0)),
            "section_fallbacks": int(synthesis_stats.get("section_fallbacks", 0)),
            "overview_fallback": bool(synthesis_stats.get("overview_fallback", False)),
            "synthesis_warnings": int(synthesis_stats.get("warnings", 0)),
            "coverage_ledger": coverage_ledger.model_dump(mode="json"),
        }

    def _validate_citations(self, citations: list[Citation]) -> list[str]:
        warnings = []
        if not citations:
            warnings.append("No source note citation was produced.")
        for citation in citations:
            if not citation.traced:
                warnings.append(f"Citation {citation.id} is not fully traced to a source note.")
        return warnings

    def _source_paths_for_card(
        self,
        card_path: str,
        frontmatter: dict,
        instance_id: str | None,
    ) -> list[str]:
        paths = []
        for source in _as_list(frontmatter.get("sources")):
            if isinstance(source, dict):
                candidate = source.get("path") or source.get("card") or source.get("title")
            else:
                candidate = source
            if candidate:
                _append_unique(paths, normalize_vault_path(str(candidate)))
        if paths:
            return paths

        params: list[Any] = [card_path]
        instance_clause = ""
        if instance_id:
            instance_clause = "AND instance_id = ?"
            params.append(instance_id)
        rows = self.db.execute(
            f"""SELECT target_path FROM relations
                WHERE source_path = ? AND rel_type = 'source_trace'
                  {instance_clause}
                ORDER BY id""",
            params,
        )
        for row in rows:
            _append_unique(paths, normalize_vault_path(row["target_path"]))
        return paths

    def _load_note(self, path: str, instance_ids: list[str] | None) -> dict | None:
        path = normalize_vault_path(path)
        params: list[Any] = [path]
        instance_clause = ""
        if instance_ids:
            placeholders = ",".join("?" * len(instance_ids))
            instance_clause = f"AND n.instance_id IN ({placeholders})"
            params.extend(instance_ids)
        rows = self.db.execute(
            f"""SELECT n.instance_id, n.file_path, n.title, n.graph_layer, n.frontmatter, i.vault_path
                FROM notes n
                JOIN instances i ON n.instance_id = i.id
                WHERE n.file_path = ?
                  {instance_clause}
                LIMIT 1""",
            params,
        )
        if not rows:
            return None
        row = rows[0]
        row["frontmatter"] = _as_frontmatter(row.get("frontmatter", {}))
        return row

    def _read_note_body(self, note: dict) -> str:
        content = self.storage.read_file(str(Path(note["vault_path"]) / note["file_path"]))
        body = extract_body(content)
        return truncate_with_marker(body, 3500)

    def _emit(
        self,
        callback: ProgressCallback | None,
        step: int,
        status: str,
        summary: dict | None = None,
    ) -> None:
        if callback is None:
            step_name = ANSWER_STEP_NAMES.get(step, f"step_{step}")
            if status == "running":
                self._step_started[step] = time.perf_counter()
                log_event(
                    logger,
                    "process.answer.step.start",
                    query_hash=self._current_query_hash,
                    step=step,
                    step_name=step_name,
                )
            elif status in {"completed", "failed"}:
                log_event(
                    logger,
                    "process.answer.step.done" if status == "completed" else "process.answer.step.error",
                    level=logging.INFO if status == "completed" else logging.ERROR,
                    query_hash=self._current_query_hash,
                    step=step,
                    step_name=step_name,
                    status=status,
                    duration_ms=_duration_ms(self._step_started.get(step, time.perf_counter())),
                    summary_keys=sorted(summary.keys()) if summary else [],
                )
        if callback:
            callback(step, status, summary)

    def _emit_thought(
        self,
        callback: ProgressCallback | None,
        step: int,
        summary: dict[str, Any],
    ) -> None:
        if callback:
            callback(step, "thought_summary", summary)


def _source_title(source_note: dict | None, path: str) -> str:
    if not source_note:
        return Path(path).stem
    fm = source_note.get("frontmatter") or {}
    return str(fm.get("doc_title") or source_note.get("title") or Path(path).stem)


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _section_ordinal(index: int) -> str:
    values = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    if 1 <= index <= len(values):
        return values[index - 1]
    return str(index)


def _as_frontmatter(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            fm, _ = parse_frontmatter(value)
            return fm
    return {}


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _unique(items) -> list[str]:
    result: list[str] = []
    for item in items:
        value = normalize_vault_path(str(item or ""))
        if value and value not in result:
            result.append(value)
    return result


def _filter_allowed_ids(values: list[str], allowed_values: list[str]) -> list[str]:
    allowed = set(allowed_values)
    return _unique(value for value in values if value in allowed)


def _limit_strings(values: list[str], max_items: int, max_chars: int) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        result.append(truncate_with_marker(text, max_chars))
        if len(result) >= max_items:
            break
    return result


def _append_unique(items: list[str], value: str) -> None:
    value = normalize_vault_path(value)
    if value and value not in items:
        items.append(value)


def _item_path(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("card") or item.get("path") or "")
    return str(item or "")
