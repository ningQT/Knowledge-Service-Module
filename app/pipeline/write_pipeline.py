"""Write pipeline - phase-two knowledge ingestion workflow."""

from __future__ import annotations

import json
import logging
import re
import time
from contextlib import nullcontext
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic_ai.settings import ModelSettings

from app.config import Settings, get_settings
from app.exceptions import PipelineCancelledException
from app.llm.agents import (
    StepDeps,
    create_step1_classify_agent,
    create_step2_path_agent,
    create_step3_source_agent,
    create_step4_filter_agent,
    create_step4_locate_agent,
    create_step5_card_agent,
    create_step6_map_agent,
    create_step7_relation_agent,
)
from app.llm.client import LLMClient
from app.llm.prompts import (
    DEFAULT_LANGUAGE,
    LANGUAGE_INSTRUCTIONS,
    PROMPTS,
    STEP4_KNOWLEDGE_LOCATE,
)
from app.llm.schemas import (
    CardFilterResult,
    CardOutput,
    DocClassification,
    KnowledgeLocateResult,
    KnowledgeMapOutput,
    KnowledgePoint,
    KnowledgePointOutput,
    MAX_CARD_CONCEPTS,
    MAX_CARD_WIKILINKS,
    MAX_MAP_KEY_RELATIONS,
    MAX_RELATION_CONNECTIONS,
    MapOutput,
    PathDecision,
    RelationDescOutput,
    RelationItem,
    STEP2_MAX_CANDIDATE_CARDS,
    SourceNoteOutput,
    StructureAnnotationOutput,
)
from app.llm.validators import (
    register_step2_validators,
    register_step4_locate_validators,
    register_step5_card_validators,
    validate_card_output,
)
from app.pipeline.relation_builder import (
    clear_wikilink_cache,
    compute_concept_overlap_for_instance,
    compute_concept_overlap_incremental,
    extract_all_relations,
)
from app.pipeline.query_dictionary import refresh_instance_dictionary
from app.schema.parser import parse_frontmatter, serialize_frontmatter
from app.schema.validator import SchemaValidator
from app.shared_infra import (
    MarkdownStructure,
    extract_key_sections,
    extract_paragraphs,
    extract_summary,
    is_fast_track,
    parse_markdown_structure,
)
from app.shared_infra.truncation import truncate_with_marker
from app.storage.database import DatabaseBackend
from app.storage.filesystem import StorageBackend
from app.storage.indexer import Indexer
from app.storage.semantic_index import SemanticIndex
from app.storage.path_utils import normalize_vault_path, validate_upload_filename
from app.observability import log_event, next_llm_call_id

logger = logging.getLogger(__name__)

SOURCE_DIR = "01-资料来源"
CARD_DIR = "02-知识卡片"
MAP_DIR = "03-知识地图"
CARD_EXTRA_SECTION_TITLES = {
    "zh": {
        "relations": "关系",
        "sources": "来源",
        "related_knowledge": "相关知识",
        "source_excerpt": "原文摘录",
        "summary": "摘要",
    },
    "en": {
        "relations": "Relations",
        "sources": "Sources",
        "related_knowledge": "Related Knowledge",
        "source_excerpt": "Source excerpt",
        "summary": "Summary",
    },
}
MAP_SECTION_TITLES = {
    "zh": {
        "topic_overview": "主题概览",
        "core_concepts": "核心概念",
        "reading_path": "推荐阅读路径",
        "key_relations": "关键关系",
        "source_materials": "来源材料",
        "linked_maps": "关联入口",
    },
    "en": {
        "topic_overview": "Topic Overview",
        "core_concepts": "Core Concepts",
        "reading_path": "Reading Path",
        "key_relations": "Key Relations",
        "source_materials": "Source Materials",
        "linked_maps": "Linked Maps",
    },
}
STEP2_MAX_EXISTING_SOURCES = 20
STEP2_MAX_TOC_HEADINGS = 30
STEP2_MAX_TOC_CHARS = 1500
FREE_TEXT_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")
STEP7_ALLOWED_RELATION_TYPES = {"dependency", "comparison", "composition", "extension"}


@dataclass
class StructuredAgentRun:
    """Structured agent output plus provider completion metadata."""

    output: Any
    finish_reason: str = ""
    usage: Any = None
    truncated: bool = False


class IngestResult:
    """Result of a write pipeline execution."""

    def __init__(self):
        self.created_files: list[str] = []
        self.updated_files: list[str] = []
        self.generated_cards: list[str] = []
        self.generated_maps: list[str] = []
        self.warnings: list[str] = []
        self.non_blocking_warnings: list[str] = []
        self.job_id: str = ""
        self.status: str = "success"

    def add_warning(self, message: str, *, non_blocking: bool = False) -> None:
        self.warnings.append(message)
        if non_blocking:
            self.non_blocking_warnings.append(message)

    def has_blocking_warnings(self) -> bool:
        return any(warning not in self.non_blocking_warnings for warning in self.warnings)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "created_files": self.created_files,
            "updated_files": self.updated_files,
            "generated_cards": self.generated_cards,
            "generated_maps": self.generated_maps,
            "warnings": self.warnings,
        }


class _FileWriteRollbackProxy:
    """Track pipeline file mutations so terminal failures can restore prior state."""

    def __init__(self, storage: StorageBackend):
        self._storage = storage
        self._originals: dict[str, str | None] = {}
        self._committed = False

    def __getattr__(self, name: str):
        return getattr(self._storage, name)

    def write_file(self, path: str, content: str) -> None:
        key = str(path)
        if key not in self._originals:
            self._originals[key] = self._storage.read_file(key) if self._storage.exists(key) else None
        self._storage.write_file(key, content)

    def delete_file(self, path: str) -> None:
        key = str(path)
        if key not in self._originals:
            self._originals[key] = self._storage.read_file(key) if self._storage.exists(key) else None
        self._storage.delete_file(key)

    def commit(self) -> None:
        self._committed = True
        self._originals.clear()

    def rollback(self) -> None:
        if self._committed:
            return
        for path, original in reversed(list(self._originals.items())):
            try:
                if original is None:
                    self._storage.delete_file(path)
                else:
                    self._storage.write_file(path, original)
            except Exception:
                logger.warning("Failed to rollback pipeline file mutation: %s", path, exc_info=True)
        self._originals.clear()


def _db_transaction(db: DatabaseBackend):
    transaction = getattr(db, "transaction", None)
    return transaction() if callable(transaction) else nullcontext()


class WritePipeline:
    """Phase-two knowledge write pipeline."""

    def __init__(
        self,
        db: DatabaseBackend,
        storage: StorageBackend,
        llm: LLMClient,
        indexer: Indexer,
        validator: SchemaValidator,
        settings: Settings | None = None,
        semantic_index: SemanticIndex | None = None,
    ):
        self.db = db
        self.storage = storage
        self.llm = llm
        self.indexer = indexer
        self.validator = validator
        self.settings = settings or get_settings()
        self.semantic_index = semantic_index
        self._current_result: IngestResult | None = None
        self._last_raw_path: str | None = None
        self._last_llm_truncated: bool = False
        self._current_instance_id: str | None = None
        self._dedup: Any = None  # Lazy-initialized SemanticDeduplicator

    def _language_instruction(self, language: str | None) -> str:
        return LANGUAGE_INSTRUCTIONS.get(
            language or DEFAULT_LANGUAGE,
            LANGUAGE_INSTRUCTIONS[DEFAULT_LANGUAGE],
        )

    def _agent_deps(
        self,
        *,
        section_id_map: dict[int, str] | None = None,
        existing_card_names: set[str] | None = None,
        point_role: str = "concept",
    ) -> StepDeps:
        return StepDeps(
            settings=self.settings,
            section_id_map=section_id_map or {},
            existing_card_names=existing_card_names or set(),
            point_role=point_role,
        )

    def _get_deduplicator(self) -> Any:
        """Return a cached SemanticDeduplicator, creating it on first use."""
        if self._dedup is None and self.semantic_index:
            from app.pipeline.semantic_dedup import SemanticDeduplicator
            self._dedup = SemanticDeduplicator(self.semantic_index, self.settings)
        return self._dedup

    def _run_structured_agent(
        self,
        agent_factory: Callable[[Settings], object],
        prompt: str,
        *,
        deps: StepDeps | None = None,
        register: Callable[[object], object] | None = None,
        step_name: str | None = None,
        retry_on_length: bool = True,
    ):
        return self._run_structured_agent_result(
            agent_factory,
            prompt,
            deps=deps,
            register=register,
            step_name=step_name,
            retry_on_length=retry_on_length,
        ).output

    def _run_structured_agent_result(
        self,
        agent_factory: Callable[[Settings], object],
        prompt: str,
        *,
        deps: StepDeps | None = None,
        register: Callable[[object], object] | None = None,
        step_name: str | None = None,
        retry_on_length: bool = True,
    ) -> StructuredAgentRun:
        step = step_name or "structured_agent"
        max_tokens = self._get_step_budget(step)
        run = self._run_structured_agent_once(
            agent_factory,
            prompt,
            deps=deps,
            register=register,
            max_tokens=max_tokens,
            call_name=step,
        )
        if run.finish_reason == "length":
            logger.warning(
                "Step %s structured output was truncated at %s tokens; usage=%s",
                step,
                max_tokens,
                run.usage,
            )
            if retry_on_length:
                retry_tokens = int(max_tokens * 1.5)
                retry = self._run_structured_agent_once(
                    agent_factory,
                    prompt,
                    deps=deps,
                    register=register,
                    max_tokens=retry_tokens,
                    call_name=f"{step}.retry",
                )
                if retry.finish_reason == "length":
                    retry.truncated = True
                    logger.warning(
                        "Step %s structured retry still truncated at %s tokens",
                        step,
                        retry_tokens,
                    )
                return retry
            run.truncated = True
        return run

    def _run_structured_agent_once(
        self,
        agent_factory: Callable[[Settings], object],
        prompt: str,
        *,
        deps: StepDeps | None = None,
        register: Callable[[object], object] | None = None,
        max_tokens: int,
        call_name: str = "structured_agent",
    ) -> StructuredAgentRun:
        llm_call_id = next_llm_call_id()
        started = time.perf_counter()
        log_event(
            logger,
            "llm.call.start",
            llm_call_id=llm_call_id,
            call_name=call_name,
            provider=self.settings.llm_provider,
            model=self.settings.llm_model,
            max_tokens=max_tokens,
        )
        try:
            agent = agent_factory(self.settings)
            if register:
                agent = register(agent)
            result = agent.run_sync(
                prompt,
                deps=deps or self._agent_deps(),
                model_settings=ModelSettings(
                    max_tokens=max_tokens,
                    temperature=self.settings.llm_temperature,
                ),
            )
            finish_reason = _finish_reason_value(getattr(result.response, "finish_reason", ""))
            usage = result.usage()
            usage_counts = _usage_counts(usage)
            log_event(
                logger,
                "llm.call.done",
                llm_call_id=llm_call_id,
                call_name=call_name,
                provider=self.settings.llm_provider,
                model=self.settings.llm_model,
                finish_reason=finish_reason,
                prompt_tokens=usage_counts["prompt_tokens"],
                completion_tokens=usage_counts["completion_tokens"],
                total_tokens=usage_counts["total_tokens"],
                usage_missing=usage_counts["total_tokens"] == 0,
                duration_ms=_duration_ms(started),
            )
            return StructuredAgentRun(
                output=result.output,
                finish_reason=finish_reason,
                usage=usage,
                truncated=finish_reason == "length",
            )
        except Exception as exc:
            log_event(
                logger,
                "llm.call.error",
                level=logging.ERROR,
                llm_call_id=llm_call_id,
                call_name=call_name,
                provider=self.settings.llm_provider,
                model=self.settings.llm_model,
                duration_ms=_duration_ms(started),
                error_type=exc.__class__.__name__,
                exc_info=True,
            )
            raise

    def _record_job(
        self,
        instance_id: str,
        input_file: str,
        result: IngestResult,
        started_at: str,
        job_id: str | None,
    ) -> None:
        """Persist terminal ingest state, including failures before Step 8."""
        final_job_id = job_id or result.job_id or f"job_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        try:
            self.db.execute(
                """INSERT OR REPLACE INTO ingest_jobs (job_id, instance_id, input_file, status,
                   created_files, updated_files, warnings, started_at, finished_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    final_job_id,
                    instance_id,
                    input_file,
                    result.status,
                    json.dumps(result.created_files, ensure_ascii=False),
                    json.dumps(result.updated_files, ensure_ascii=False),
                    json.dumps(result.warnings, ensure_ascii=False),
                    started_at,
                    datetime.now(UTC).isoformat(),
                ),
            )
        except Exception as e:
            logger.warning("Failed to record job %s: %s", final_job_id, e)
        result.job_id = final_job_id

    def execute(
        self,
        instance_id: str,
        vault_path: str,
        markdown: str,
        filename: str,
        domain_hint: str | None = None,
        auto_map: bool = True,
        language: str = DEFAULT_LANGUAGE,
        progress_callback: Callable[[int, str, dict | None], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        job_id: str | None = None,
    ) -> IngestResult:
        """Execute ingestion without changing the public ingest API."""
        result = IngestResult()
        self._current_result = result  # PIT-14: Allow card generation to update status
        self._current_instance_id = instance_id
        language_instruction = self._language_instruction(language)
        now = datetime.now(UTC).isoformat()
        map_path = None
        source_path = filename
        source_content = markdown
        card_paths: list[str] = []
        card_contents: list[str] = []
        step_started: dict[int, float] = {}
        original_storage = self.storage
        file_journal = _FileWriteRollbackProxy(original_storage)
        self.storage = file_journal

        def _cb(step: int, status: str, summary: dict | None = None):
            if progress_callback is None:
                if status == "running":
                    step_started[step] = time.perf_counter()
                    log_event(
                        logger,
                        "process.ingest.step.start",
                        job_id=job_id,
                        instance_id=instance_id,
                        step=step,
                    )
                elif status in {"completed", "failed"}:
                    log_event(
                        logger,
                        "process.ingest.step.done" if status == "completed" else "process.ingest.step.error",
                        level=logging.INFO if status == "completed" else logging.ERROR,
                        job_id=job_id,
                        instance_id=instance_id,
                        step=step,
                        status=status,
                        duration_ms=_duration_ms(step_started.get(step, time.perf_counter())),
                        summary_keys=sorted(summary.keys()) if summary else [],
                    )
            if progress_callback:
                progress_callback(step, status, summary)

        def _check_cancel():
            if cancel_check and cancel_check():
                raise PipelineCancelledException()

        try:
            _check_cancel()
            _cb(1, "running")
            logger.info("Step 1: structure-aware classification for %s", filename)
            classification, doc_structure, _ = self._phase1_structure_aware(
                markdown, filename, domain_hint, language_instruction
            )
            _cb(1, "completed", {
                "doc_type": classification.doc_type,
                "domain": classification.domain,
                "kind": classification.kind,
                "size_tier": doc_structure.size_tier.value if hasattr(doc_structure.size_tier, 'value') else str(doc_structure.size_tier),
            })

            _check_cancel()
            _cb(2, "running")
            logger.info("Step 2: path decision for %s", filename)
            path_decision = self._step2_path_decision(
                filename, classification, vault_path, doc_structure, language_instruction,
                source_content=markdown,
            )
            _cb(2, "completed", {
                "source_name": path_decision.source_name,
                "candidate_cards_count": len(path_decision.candidate_cards),
            })

            _check_cancel()
            _cb(3, "running")
            logger.info("Step 3: source note v2")

            # PIT-04: Check if we can reuse an existing source
            skip_step3 = False
            if path_decision.existing_source:
                existing_source_path = self._find_existing_source(vault_path, path_decision.existing_source)
                if existing_source_path:
                    logger.info("Reusing existing source: %s", path_decision.existing_source)
                    source_path = existing_source_path
                    source_content = self.storage.read_file(str(Path(vault_path) / source_path))
                    # Parse existing source to get source_output
                    source_fm, _ = parse_frontmatter(source_content)
                    source_output = SourceNoteOutput(
                        title=source_fm.get("doc_title", path_decision.existing_source),
                        summary=source_fm.get("doc_summary", ""),
                        extractable_knowledge_points=source_fm.get("extractable_knowledge_points", []),
                        concepts=source_fm.get("concepts", []),
                    )
                    skip_step3 = True
                    _cb(3, "completed", {
                        "title": source_output.title,
                        "summary": source_output.summary[:100],
                        "concepts_count": len(source_output.concepts),
                        "reused": True,
                    })

            if not skip_step3:
                source_path, source_content, source_output = self._step3_generate_source_v2(
                    vault_path,
                    filename,
                    markdown,
                    classification,
                    path_decision,
                    doc_structure,
                    language_instruction,
                )
                result.created_files.append(source_path)
                if self._last_raw_path:
                    result.created_files.append(self._last_raw_path)
                _cb(3, "completed", {
                    "title": source_output.title,
                    "summary": source_output.summary[:100],
                    "concepts_count": len(source_output.concepts),
                })

            fast_track = is_fast_track(doc_structure.size_tier)
            if fast_track:
                _check_cancel()
                _cb(4, "running")
                logger.info("Step 4: fast-track card filtering")
                filter_result = self._step4_filter_cards(
                    classification, path_decision, vault_path, language_instruction
                )
                _cb(4, "completed", {"selected_cards_count": len(filter_result.selected)})
                _check_cancel()
                _cb(5, "running")
                card_paths, card_contents = self._step5_generate_cards(
                    vault_path, markdown, classification, filter_result, source_path, language_instruction
                )
                _cb(5, "completed", {
                    "card_count": len(card_paths),
                    "card_titles": [Path(p).stem for p in card_paths],
                })
            else:
                _check_cancel()
                _cb(4, "running")
                logger.info("Step 4: phase-two knowledge location")
                knowledge_map = self._phase2_knowledge_locate(
                    markdown, doc_structure, classification, path_decision, vault_path, language_instruction
                )
                if not knowledge_map.knowledge_points:
                    knowledge_map = self._fallback_full_extract(path_decision, doc_structure)
                _cb(4, "completed", {"total_points": knowledge_map.total_points})
                _check_cancel()
                _cb(5, "running")
                logger.info("Step 5: phase-three knowledge extraction")
                card_paths, card_contents = self._phase3_knowledge_extract(
                    vault_path, markdown, doc_structure, classification, knowledge_map, source_path, language_instruction
                )
                _cb(5, "completed", {
                    "card_count": len(card_paths),
                    "card_titles": [Path(p).stem for p in card_paths],
                })

            result.created_files.extend(card_paths)
            result.generated_cards = card_paths

            _check_cancel()
            if auto_map:
                _cb(6, "running")
                if not card_paths:
                    warning = "Step 6 map generation skipped because no cards were generated."
                    logger.warning(warning)
                    result.warnings.append(warning)
                    _cb(6, "completed", {"map_title": None, "core_concepts_count": 0})
                else:
                    logger.info("Step 6: knowledge map v2 (FR-06 forced output)")
                    map_path, map_content = self._step6_generate_map_v2(
                        vault_path,
                        classification,
                        card_paths,
                        card_contents,
                        source_path,
                        source_output,
                        language_instruction,
                    )
                    if map_path:
                        result.created_files.append(map_path)
                        result.generated_maps.append(map_path)
                        _cb(6, "completed", {
                            "map_title": Path(map_path).stem,
                            "core_concepts_count": len(classification.topics),
                        })
                    else:
                        _cb(6, "completed", {"map_title": None, "core_concepts_count": 0})
            else:
                _cb(6, "completed", {"skipped": True})

            _check_cancel()
            _cb(7, "running")
            logger.info("Step 7: relation description")
            rel_count = self._step7_relation_description(
                vault_path, classification, card_paths, card_contents, source_path, language_instruction
            )
            _cb(7, "completed", {"relation_count": rel_count})

            _check_cancel()
            _cb(8, "running")
            logger.info("Step 8: archiving and indexing")
            with _db_transaction(self.db):
                self._step8_archive_and_index(
                    instance_id,
                    vault_path,
                    source_path,
                    source_content,
                    card_paths,
                    card_contents,
                    map_path,
                    result,
                    now,
                    job_id,
                    classification,
                )
            _cb(8, "completed", {"indexed_files_count": len(result.created_files)})
            file_journal.commit()
        except PipelineCancelledException:
            result.status = "cancelled"
            file_journal.rollback()
            self._record_job(instance_id, source_path, result, now, job_id)
            raise
        except Exception as e:
            logger.error("Write pipeline failed: %s", e)
            result.status = "failed"
            result.warnings.append(str(e))
            file_journal.rollback()
            self._record_job(instance_id, source_path, result, now, job_id)
        finally:
            self.storage = original_storage
            self._current_instance_id = None

        return result

    def _phase1_structure_aware(
        self,
        content: str,
        filename: str,
        domain_hint: str | None,
        language_instruction: str,
    ) -> tuple[DocClassification, MarkdownStructure, StructureAnnotationOutput | None]:
        """Parse the whole document and classify it.

        PIT-01: Removed unused annotation LLM call to save token and latency.
        The annotation result was never consumed by downstream steps.
        """
        # PIT-02: Use configurable paper detection patterns
        is_paper = any(filename.lower().endswith(p) for p in self.settings.paper_filename_patterns)
        max_level = self.settings.paper_max_level if is_paper else self.settings.default_max_level
        structure = parse_markdown_structure(content, mode="full", max_level=max_level)
        classification = self._step1_classify(content, filename, domain_hint, language_instruction)
        # PIT-01: annotation removed — was never consumed by downstream steps
        return classification, structure, None

    def _step1_classify(
        self, content: str, filename: str, domain_hint: str | None, language_instruction: str
    ) -> DocClassification:
        structure = parse_markdown_structure(content, mode="lite")
        classify_content = self._build_overview_context(
            content,
            structure,
            keywords=[filename, domain_hint or ""],
            intent_type="topic_scan",
            summary_chars=1200,
        )

        prompt = PROMPTS["classify"].format(
            content=classify_content,
            language_instruction=language_instruction,
        )
        result = self._run_structured_agent(
            create_step1_classify_agent,
            prompt,
            step_name="step1_classify",
        )
        if domain_hint:
            result.domain = domain_hint
        return result

    def _find_existing_source(self, vault_path: str, source_name: str) -> str | None:
        """PIT-04: Find an existing source note by name."""
        source_dir = str(Path(vault_path) / SOURCE_DIR)
        files = self.storage.list_files(source_dir, "*.md")
        for f in files:
            if Path(f).stem == source_name:
                return f"{SOURCE_DIR}/{Path(f).name}"
        return None

    def _step2_path_decision(
        self, filename: str, classification: DocClassification, vault_path: str,
        structure: MarkdownStructure | None = None,
        language_instruction: str = "",
        source_content: str = "",
    ) -> PathDecision:
        existing = self.storage.list_files(str(Path(vault_path) / SOURCE_DIR), "*.md")
        existing = existing[:STEP2_MAX_EXISTING_SOURCES]
        prompt = PROMPTS["path_decision"].format(
            filename=filename,
            classification=classification.model_dump_json(),
            existing_sources=json.dumps(existing, ensure_ascii=False),
            language_instruction=language_instruction,
        )

        # OBS-05: Inject document TOC to help LLM generate better candidate_cards
        if structure and structure.headings:
            toc_lines = [
                f"{'  ' * (h.level - 1)}{h.title}"
                for h in structure.headings[:STEP2_MAX_TOC_HEADINGS]
            ]
            toc_text = truncate_with_marker("\n".join(toc_lines), STEP2_MAX_TOC_CHARS)
            if toc_text:
                prompt += f"\n\n文档目录结构：\n{toc_text}"
        try:
            path_decision = self._run_structured_agent(
                create_step2_path_agent,
                prompt,
                register=register_step2_validators,
                step_name="step2_path_decision",
            )
        except Exception as exc:
            logger.warning("Step 2 path decision failed; using fallback: %s", exc)
            if self._current_result is not None:
                self._current_result.warnings.append(
                    f"Step 2 path decision fallback used: {type(exc).__name__}"
                )
            path_decision = self._fallback_path_decision(filename, classification, structure)

        # Semantic dedup: check if a similar source already exists
        if self.semantic_index and self._current_instance_id:
            try:
                dedup = self._get_deduplicator()
                dup_path = dedup.find_duplicate_source(
                    self._current_instance_id,
                    new_title=path_decision.source_name,
                    new_summary=truncate_with_marker(source_content, 500),
                    new_concepts=classification.topics,
                )
                if dup_path and not path_decision.existing_source:
                    path_decision.existing_source = dup_path
                    logger.info(
                        "Semantic dedup: found duplicate source %s for '%s'",
                        dup_path,
                        path_decision.source_name,
                    )
            except Exception as e:
                logger.warning("Semantic dedup check in step 2 failed (non-critical): %s", e)

        return path_decision

    def _fallback_path_decision(
        self,
        filename: str,
        classification: DocClassification,
        structure: MarkdownStructure | None,
    ) -> PathDecision:
        candidates: list[str] = []
        for value in [*classification.topics, classification.domain, classification.kind]:
            name = _safe_name(str(value))
            if name and name not in candidates:
                candidates.append(name)
            if len(candidates) >= STEP2_MAX_CANDIDATE_CARDS:
                break
        if structure:
            for heading in structure.headings:
                name = _safe_name(heading.title)
                if name and name not in candidates:
                    candidates.append(name)
                if len(candidates) >= STEP2_MAX_CANDIDATE_CARDS:
                    break
        if not candidates:
            candidates.append(_safe_name(Path(filename).stem) or "文档概览")
        return PathDecision(
            source_name=_safe_name(Path(filename).stem) or "source",
            existing_source=None,
            candidate_cards=candidates[:STEP2_MAX_CANDIDATE_CARDS],
        )

    def _step3_generate_source_v2(
        self,
        vault_path: str,
        filename: str,
        content: str,
        classification: DocClassification,
        path_decision: PathDecision,
        structure: MarkdownStructure,
        language_instruction: str,
    ) -> tuple[str, str, SourceNoteOutput]:
        source_context = self._build_source_note_context(content, structure)
        prompt = PROMPTS["source_note"].format(
            filename=filename,
            domain=classification.domain,
            content=source_context,
            language_instruction=language_instruction,
        )
        output = self._run_structured_agent(
            create_step3_source_agent,
            prompt,
            step_name="step3_source_note",
        )

        filename = validate_upload_filename(filename)
        raw_dir = str(Path(vault_path) / SOURCE_DIR / "raw")
        self.storage.create_directory(raw_dir)
        raw_path = f"{SOURCE_DIR}/raw/{filename}"

        # PIT-08: Check for existing raw file and add timestamp if needed
        if self.storage.exists(str(Path(vault_path) / raw_path)):
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            name_stem = Path(filename).stem
            name_ext = Path(filename).suffix
            raw_path = f"{SOURCE_DIR}/raw/{name_stem}_{ts}{name_ext}"
            logger.info("Raw file conflict, renamed to: %s", Path(raw_path).name)

        self.storage.write_file(str(Path(vault_path) / raw_path), content)
        self._last_raw_path = raw_path

        source_name = _safe_name(path_decision.source_name)
        source_rel_path = f"{SOURCE_DIR}/{source_name}.md"
        source_fm = {
            "type": "source",
            "domain": classification.domain,
            "kind": classification.kind,
            "graph_layer": 1,
            "graph_role": "source",
            "verification": "unverified",
            "status": "active",
            "original_doc": raw_path,
            "extracted_cards": [],
            "card_count": 0,
            "concepts": _truncate_list(output.concepts, 15),
            "doc_title": output.title,
            "doc_summary": truncate_with_marker(output.summary, 2000),
            "doc_type": classification.doc_type,
            "main_topic": classification.topics[0] if classification.topics else "",
            "extractable_knowledge_points": _truncate_list(
                output.extractable_knowledge_points, 20
            ),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        source_fm = self._truncate_source_note_fields(source_fm)
        source_content = serialize_frontmatter(source_fm, content)
        self.storage.write_file(str(Path(vault_path) / source_rel_path), source_content)
        return source_rel_path, source_content, output

    def _step4_filter_cards(
        self,
        classification: DocClassification,
        path_decision: PathDecision,
        vault_path: str,
        language_instruction: str,
    ) -> CardFilterResult:
        existing = self.storage.list_files(str(Path(vault_path) / CARD_DIR), "*.md")
        prompt = PROMPTS["filter_cards"].format(
            knowledge_points=json.dumps(path_decision.candidate_cards, ensure_ascii=False),
            existing_cards=json.dumps(existing, ensure_ascii=False),
            language_instruction=language_instruction,
        )
        return self._run_structured_agent(
            create_step4_filter_agent,
            prompt,
            step_name="step4_filter_cards",
        )

    def _phase2_knowledge_locate(
        self,
        content: str,
        structure: MarkdownStructure,
        classification: DocClassification,
        path_decision: PathDecision,
        vault_path: str,
        language_instruction: str,
    ) -> KnowledgeLocateResult:
        existing = self.storage.list_files(str(Path(vault_path) / CARD_DIR), "*.md")
        body_context = self._build_locate_context(content, structure, classification)

        # PIT-10: Build section_id mapping for LLM
        section_id_map = {h.section_id: h.title for h in structure.headings}
        section_map_text = "\n".join(
            f"  [section_id={sid}] {title}" for sid, title in sorted(section_id_map.items())
        )

        prompt = STEP4_KNOWLEDGE_LOCATE.format(
            classification=classification.model_dump_json(),
            candidate_cards=json.dumps(path_decision.candidate_cards, ensure_ascii=False),
            existing_cards=json.dumps(existing, ensure_ascii=False),
            section_map_text=section_map_text,
            body_context=body_context,
            language_instruction=language_instruction,
        )
        try:
            result = self._run_structured_agent(
                create_step4_locate_agent,
                prompt,
                deps=self._agent_deps(section_id_map=section_id_map),
                register=register_step4_locate_validators,
                step_name="step4_knowledge_locate",
            )
        except Exception as e:
            logger.warning("Step 4 locate failed after structured retries; using fallback: %s", e)
            return self._fallback_full_extract(path_decision, structure)

        # Semantic dedup: filter knowledge points similar to existing notes
        if self.semantic_index and self._current_instance_id and result.knowledge_points:
            threshold = self.settings.dedup_card_threshold
            kept: list = []
            for kp in result.knowledge_points:
                query_text = f"{kp.name}\n{kp.section_title or ''}"
                similar = self.semantic_index.find_similar(
                    self._current_instance_id,
                    query_text,
                    threshold=threshold,
                    top_k=1,
                )
                if similar:
                    logger.info(
                        "Semantic dedup: rejecting knowledge point '%s' (similar to %s, score=%.4f)",
                        kp.name,
                        similar[0]["file_path"],
                        similar[0]["score"],
                    )
                    result.rejected.append(kp.name)
                else:
                    kept.append(kp)
            if len(kept) != len(result.knowledge_points):
                result.knowledge_points = kept
                result.total_points = len(kept)

        return result

    def _fallback_full_extract(
        self, path_decision: PathDecision, structure: MarkdownStructure
    ) -> KnowledgeLocateResult:
        """PIT-13: Improved fallback that generates knowledge points from headings.

        Instead of using candidate_cards (which may be low quality guesses),
        generate knowledge points directly from document structure.
        """
        points = []
        headings = structure.headings or []

        # Use headings to generate knowledge points
        for heading in headings[:10]:  # Limit to 10 headings
            # Skip very short or generic headings
            if len(heading.title.strip()) < 3:
                continue
            points.append(
                KnowledgePoint(
                    name=heading.title,
                    section_id=heading.section_id,
                    section_title=heading.title,
                    estimated_tokens=0,
                )
            )

        # If no valid headings, fall back to candidate_cards
        if not points and path_decision.candidate_cards:
            for title in path_decision.candidate_cards[:5]:
                points.append(
                    KnowledgePoint(
                        name=title,
                        section_id=0,
                        section_title="",
                        estimated_tokens=0,
                    )
                )

        return KnowledgeLocateResult(
            knowledge_points=points,
            total_points=len(points),
            density_map={},
        )

    def _step5_generate_cards(
        self,
        vault_path: str,
        content: str,
        classification: DocClassification,
        filter_result: CardFilterResult,
        source_path: str,
        language_instruction: str,
    ) -> tuple[list[str], list[str]]:
        points = [
            KnowledgePointOutput(
                card_title=point,
                section_id=0,
                para_range=[0, 0],
                concepts=[point],
                extraction_confidence="medium",
            )
            for point in filter_result.selected
        ]
        return self._generate_cards_from_points(
            vault_path,
            content,
            None,
            classification,
            points,
            source_path,
            fast_context=content,
            language_instruction=language_instruction,
        )

    def _phase3_knowledge_extract(
        self,
        vault_path: str,
        content: str,
        structure: MarkdownStructure,
        classification: DocClassification,
        knowledge_map: KnowledgeLocateResult,
        source_path: str,
        language_instruction: str,
    ) -> tuple[list[str], list[str]]:
        # Convert lightweight KnowledgePoint to detailed KnowledgePointOutput
        points = [
            KnowledgePointOutput(
                card_title=kp.name,
                section_id=kp.section_id or 0,
                para_range=_para_range_for_section(kp.section_id, structure),
                concepts=[kp.name],
                role="concept",
                extraction_confidence="medium",
            )
            for kp in knowledge_map.knowledge_points
        ]
        return self._generate_cards_from_points(
            vault_path,
            content,
            structure,
            classification,
            points,
            source_path,
            language_instruction=language_instruction,
        )

    def _generate_cards_from_points(
        self,
        vault_path: str,
        content: str,
        structure: MarkdownStructure | None,
        classification: DocClassification,
        points: list[KnowledgePointOutput],
        source_path: str,
        fast_context: str | None = None,
        language_instruction: str = "",
    ) -> tuple[list[str], list[str]]:
        card_paths: list[str] = []
        card_contents: list[str] = []
        failed_count = 0
        draft_count = 0
        total_count = len(points)

        for point in points:
            context = fast_context
            if context is None:
                try:
                    context = extract_paragraphs(
                        content, structure, point.para_range, buffer=1
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to extract context for '%s'; using document preview: %s",
                        point.card_title,
                        e,
                    )
                    context = truncate_with_marker(content, 1200)
            try:
                prompt = PROMPTS["generate_card"].format(
                    knowledge_point=point.card_title,
                    domain=classification.domain,
                    classification=classification.model_dump_json(),
                    context=context,
                    language_instruction=language_instruction,
                )
                card_truncated = False
                existing_card_names = self._collect_existing_card_names(
                    vault_path, card_paths, points
                )
                card_run = self._run_structured_agent_result(
                    create_step5_card_agent,
                    prompt,
                    deps=self._agent_deps(
                        existing_card_names=existing_card_names,
                        point_role=point.role or "concept",
                    ),
                    register=register_step5_card_validators,
                    step_name="step5_generate_card",
                    retry_on_length=True,
                )
                card_output = card_run.output
                card_truncated = card_run.truncated
                errors, warnings = self._validate_card_quality(card_output)
                verification = "truncated" if card_truncated else "unverified"

                # Semantic dedup: check if card should merge with existing
                dedup_action = "create"
                merge_target_path = ""
                if self.semantic_index and self._current_instance_id:
                    try:
                        dedup = self._get_deduplicator()
                        dedup_action, merge_target_path = dedup.should_merge_or_create(
                            self._current_instance_id,
                            new_card_title=card_output.title,
                            new_card_summary=card_output.summary,
                        )
                    except Exception as e:
                        logger.warning(
                            "Semantic dedup merge check failed for '%s' (non-critical): %s",
                            card_output.title,
                            e,
                        )
                        dedup_action = "create"

                if dedup_action == "merge" and merge_target_path:
                    # Merge: update existing card's frontmatter with new source and concepts
                    try:
                        existing_content = self.storage.read_file(
                            str(Path(vault_path) / merge_target_path)
                        )
                        exist_fm, exist_body = parse_frontmatter(existing_content)
                        # Add new source to sources list
                        exist_sources = exist_fm.get("sources", [])
                        if source_path and source_path not in exist_sources:
                            exist_sources.append(source_path)
                        exist_fm["sources"] = exist_sources
                        # Merge concepts
                        exist_concepts = exist_fm.get("concepts", [])
                        new_concepts = card_output.concepts or point.concepts
                        for c in new_concepts:
                            if c not in exist_concepts:
                                exist_concepts.append(c)
                        exist_fm["concepts"] = _truncate_list(exist_concepts, MAX_CARD_CONCEPTS)
                        exist_fm["updated_at"] = datetime.now(UTC).isoformat()
                        updated_card = serialize_frontmatter(exist_fm, exist_body)
                        self.storage.write_file(
                            str(Path(vault_path) / merge_target_path), updated_card
                        )
                        card_paths.append(merge_target_path)
                        card_contents.append(updated_card)
                        logger.info(
                            "Semantic dedup: merged '%s' into existing %s",
                            card_output.title,
                            merge_target_path,
                        )
                        if self._current_result is not None:
                            self._current_result.updated_files.append(merge_target_path)
                        # Skip the rest of the card creation loop iteration
                        continue
                    except Exception as e:
                        logger.warning(
                            "Failed to merge card '%s' into %s, creating new: %s",
                            card_output.title,
                            merge_target_path,
                            e,
                        )
                        dedup_action = "create"

                # If we reach here, action is "create" - proceed as before
                logger.info("Semantic dedup: creating new card '%s'", card_output.title)
                if card_truncated:
                    warning = f"Card '{point.card_title}' output was truncated after retry"
                    warnings.append(warning)
                    if self._current_result is not None:
                        self._current_result.warnings.append(warning)

                card_name = _safe_name(card_output.title)
                card_rel_path = f"{CARD_DIR}/{card_name}.md"
                concepts = card_output.concepts or point.concepts
                # PIT-16: Ensure graph_role consistency with KnowledgePoint.role
                graph_role = point.role if point.role else card_output.graph_role

                card_fm = {
                    "type": "card",
                    "domain": classification.domain,
                    "kind": classification.kind,
                    "graph_layer": 2,
                    "graph_role": graph_role,
                    "verification": verification,
                    "status": "active",
                    "sources": [source_path],
                    "concepts": _truncate_list(concepts, MAX_CARD_CONCEPTS),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
                section_titles = _card_extra_section_titles(language_instruction)
                body_parts = [
                    f"# {card_output.title}",
                    "",
                    _strip_free_text_wikilinks(card_output.summary),
                ]
                for section in card_output.sections:
                    heading = _strip_free_text_wikilinks(section.heading).strip()
                    content_text = _strip_free_text_wikilinks(section.content).strip()
                    if heading and content_text:
                        body_parts.extend(["", f"## {heading}", "", content_text])
                relations_text = _strip_free_text_wikilinks(card_output.relations).strip()
                if relations_text:
                    body_parts.extend(["", f"## {section_titles['relations']}", "", relations_text])
                sources_text = _strip_free_text_wikilinks(card_output.sources_text).strip()
                if sources_text:
                    body_parts.extend(["", f"## {section_titles['sources']}", "", sources_text])
                # PIT-17: Validate wikilinks - filter out non-existent targets
                if card_output.wikilinks:
                    # Get existing card names from vault AND current batch
                    existing_cards = set()
                    # Cards already in the vault
                    try:
                        vault_card_files = self.storage.list_files(
                            str(Path(vault_path) / CARD_DIR), "*.md"
                        )
                        for f in vault_card_files:
                            existing_cards.add(Path(f).stem)
                    except Exception:
                        pass
                    # Cards created in current batch
                    for p in card_paths:
                        existing_cards.add(Path(p).stem)
                    # Knowledge points from current batch
                    for pt in points:
                        if hasattr(pt, 'card_title'):
                            existing_cards.add(pt.card_title)

                    # Filter wikilinks to only include existing cards
                    valid_wikilinks = [
                        w for w in card_output.wikilinks[:MAX_CARD_WIKILINKS]
                        if w in existing_cards
                    ]
                    if valid_wikilinks:
                        body_parts.extend(["", f"## {section_titles['related_knowledge']}", ""])
                        body_parts.extend(f"- [[{link}]]" for link in valid_wikilinks)

                card_content = serialize_frontmatter(card_fm, "\n".join(body_parts))
                schema_warnings = self.validator.validate(card_fm)
                for warning in [*warnings, *schema_warnings]:
                    logger.warning("Card validation warning for %s: %s", card_name, warning)
                self.storage.write_file(str(Path(vault_path) / card_rel_path), card_content)
                card_paths.append(card_rel_path)
                card_contents.append(card_content)

                # Semantic index: update embedding for newly created card
                if self.semantic_index and self._current_instance_id:
                    try:
                        self.semantic_index.add_note(
                            self._current_instance_id,
                            card_rel_path,
                            title=card_output.title,
                            summary=card_output.summary,
                            concepts=card_output.concepts or point.concepts,
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to update semantic index for card '%s' (non-critical): %s",
                            card_output.title,
                            e,
                        )
            except Exception as e:
                failed_count += 1
                message = f"Failed to generate card for '{point.card_title}': {e}"
                logger.error(message)
                if self._current_result is not None:
                    self._current_result.warnings.append(message)
                try:
                    draft_path, draft_content = self._write_draft_card(
                        vault_path=vault_path,
                        point=point,
                        classification=classification,
                        source_path=source_path,
                        context=context or content,
                        language_instruction=language_instruction,
                    )
                    card_paths.append(draft_path)
                    card_contents.append(draft_content)
                    draft_count += 1
                    draft_message = (
                        f"Generated draft fallback card for '{point.card_title}' after Step 5 failure"
                    )
                    logger.warning(draft_message)
                    if self._current_result is not None:
                        self._current_result.warnings.append(draft_message)
                except Exception as draft_error:
                    draft_message = (
                        f"Failed to generate draft fallback card for "
                        f"'{point.card_title}': {draft_error}"
                    )
                    logger.error(draft_message)
                    if self._current_result is not None:
                        self._current_result.warnings.append(draft_message)

        # PIT-14: Mark partial_failed when all cards fail
        if failed_count > 0:
            if self._current_result is not None:
                self._current_result.status = "partial_failed"
            if failed_count == total_count:
                logger.warning(
                    "All %d card LLM generations failed; %d draft fallback card(s) generated",
                    total_count,
                    draft_count,
                )
            else:
                logger.warning(
                    "%d/%d card LLM generations failed; %d draft fallback card(s) generated",
                    failed_count,
                    total_count,
                    draft_count,
                )

        return card_paths, card_contents

    def _write_draft_card(
        self,
        *,
        vault_path: str,
        point: KnowledgePointOutput,
        classification: DocClassification,
        source_path: str,
        context: str,
        language_instruction: str,
    ) -> tuple[str, str]:
        card_name = _safe_name(point.card_title)
        card_rel_path = f"{CARD_DIR}/{card_name}.md"
        concepts = _truncate_list(
            point.concepts or [point.card_title, classification.domain],
            MAX_CARD_CONCEPTS,
        )
        if not concepts:
            concepts = [card_name]
        graph_role = point.role if point.role in {"concept", "method"} else "concept"

        card_fm = {
            "type": "card",
            "domain": classification.domain,
            "kind": classification.kind,
            "graph_layer": 2,
            "graph_role": graph_role,
            "verification": "draft",
            "status": "active",
            "sources": [source_path],
            "concepts": concepts,
            "updated_at": datetime.now(UTC).isoformat(),
        }

        excerpt = truncate_with_marker((context or point.reason or point.card_title).strip(), 800)
        if _prefers_english(language_instruction):
            summary = (
                "Draft fallback card generated because structured LLM card generation failed. "
                f"Original knowledge point: {point.card_title}."
            )
            excerpt_heading = "Source excerpt"
            sources_heading = "Sources"
        else:
            summary = (
                "由于结构化 LLM 卡片生成失败，系统生成了这张 draft 兜底卡片。"
                f"原始知识点：{point.card_title}。"
            )
            excerpt_heading = "原文摘录"
            sources_heading = "来源"

        body_parts = [
            f"# {card_name}",
            "",
            summary,
            "",
            f"## {excerpt_heading}",
            "",
            excerpt,
            "",
            f"## {sources_heading}",
            "",
            f"- [[{source_path}]]",
        ]

        card_content = serialize_frontmatter(card_fm, "\n".join(body_parts))
        warnings = self.validator.validate(card_fm)
        for warning in warnings:
            logger.warning("Draft card validation warning for %s: %s", card_name, warning)
        self.storage.write_file(str(Path(vault_path) / card_rel_path), card_content)
        return card_rel_path, card_content

    def _step6_generate_map_v2(
        self,
        vault_path: str,
        classification: DocClassification,
        card_paths: list[str],
        card_contents: list[str],
        source_path: str,
        source_output: SourceNoteOutput,
        language_instruction: str,
    ) -> tuple[str | None, str | None]:
        card_summaries = self._build_card_summaries(card_paths, card_contents)
        source_ref = _canonical_source_material(source_path, source_output, [])
        prompt = PROMPTS["generate_map"].format(
            topic=classification.topics[0] if classification.topics else classification.domain,
            domain=classification.domain,
            cards=json.dumps(card_summaries, ensure_ascii=False),
            source_ref=json.dumps(source_ref, ensure_ascii=False),
            summary=source_output.summary,
            language_instruction=language_instruction,
        )
        try:
            output = self._run_structured_agent(
                create_step6_map_agent,
                prompt,
                step_name="step6_generate_map",
            )

            # PIT-19: Improved fallback for core_concepts with better role distribution
            if output.core_concepts:
                core_concepts = output.core_concepts
            else:
                # Assign roles: first 1-2 as "core", rest as "normal"
                core_count = min(2, len(card_summaries))
                core_concepts = [
                    {
                        "title": item["title"],
                        "role": "core" if i < core_count else "normal",
                        "card": item["path"],
                        "summary": item["summary"],
                    }
                    for i, item in enumerate(card_summaries)
                ]

            # PIT-19: Improved fallback for reading_path
            if output.reading_path:
                reading_path = output.reading_path
            else:
                reading_path = [
                    {"order": i + 1, "title": item["title"], "card": item["path"], "reason": ""}
                    for i, item in enumerate(card_summaries)
                ]

            core_concepts = _canonicalize_card_references(core_concepts, card_summaries)
            reading_path = _canonicalize_card_references(reading_path, card_summaries)
            source_materials = [
                _canonical_source_material(source_path, source_output, output.source_materials)
            ]
            linked_maps = _canonicalize_linked_maps(output.linked_maps, vault_path, self.storage)
            map_name = _safe_name(output.title)
            map_rel_path = f"{MAP_DIR}/{map_name}.md"
            # PIT-20: Filter empty fields and limit key_relations
            map_fm = {
                "type": "map",
                "domain": classification.domain,
                "kind": classification.kind,
                "graph_layer": 3,
                "graph_role": "index",
                "verification": "verified",
                "status": "active",
                "concepts": output.concepts,
                "core_concepts": core_concepts,
                "reading_path": reading_path,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            # Only add non-empty optional fields
            if output.key_relations:
                map_fm["key_relations"] = output.key_relations[:MAX_MAP_KEY_RELATIONS]
            if source_materials:
                map_fm["source_materials"] = source_materials
            if linked_maps:
                map_fm["linked_maps"] = linked_maps
            map_content = serialize_frontmatter(
                map_fm,
                _build_map_body(
                    output,
                    core_concepts,
                    reading_path,
                    source_materials,
                    linked_maps,
                    language_instruction,
                ),
            )
            warnings = self.validator.validate(map_fm)
            for warning in warnings:
                logger.warning("Map validation warning for %s: %s", map_name, warning)
            self.storage.write_file(str(Path(vault_path) / map_rel_path), map_content)
            return map_rel_path, map_content
        except Exception as e:
            message = f"Step 6 map generation failed: {e}"
            logger.error(message)
            if self._current_result is not None:
                self._current_result.warnings.append(message)
            return None, None

    def _step7_relation_description(
        self,
        vault_path: str,
        classification: DocClassification,
        card_paths: list[str],
        card_contents: list[str],
        source_path: str,
        language_instruction: str,
    ) -> int:
        """Step 7: Generate relation descriptions for the new knowledge. Returns relation count."""
        if not card_paths:
            return 0

        card_titles = [Path(p).stem for p in card_paths]
        prompt = PROMPTS["relation_desc"].format(
            new_cards=json.dumps(card_titles, ensure_ascii=False),
            domain=classification.domain,
            kind=classification.kind,
            topics=json.dumps(classification.topics[:5], ensure_ascii=False),
            language_instruction=language_instruction,
        )
        try:
            run = self._run_structured_agent_result(
                create_step7_relation_agent,
                prompt,
                step_name="step7_relation_desc",
            )
            if run.truncated:
                raise RuntimeError("Step 7 relation output was truncated after retry")
            connections = self._filter_step7_connections(
                run.output,
                card_titles,
                language_instruction,
            )
            return self._apply_relation_descriptions(
                vault_path,
                card_paths,
                card_contents,
                connections,
            )
        except Exception as e:
            message = (
                "Step 7 relation description failed (non-critical); "
                f"using rule fallback: {e}"
            )
            logger.warning(message)
            if self._current_result is not None:
                self._current_result.add_warning(message, non_blocking=True)
            connections = self._fallback_relation_descriptions(
                card_paths,
                card_contents,
                language_instruction,
            )
            return self._apply_relation_descriptions(
                vault_path,
                card_paths,
                card_contents,
                connections,
            )

    def _filter_step7_connections(
        self,
        output: RelationDescOutput,
        card_titles: list[str],
        language_instruction: str,
    ) -> list[RelationItem]:
        allowed_titles = set(card_titles)
        filtered: list[RelationItem] = []
        seen: set[tuple[str, str, str]] = set()

        for connection in output.new_connections:
            source = str(connection.source or "").strip()
            target = str(connection.target or "").strip()
            relation_type = _normalize_relation_type(connection.relation_type)
            if (
                source not in allowed_titles
                or target not in allowed_titles
                or source == target
                or relation_type not in STEP7_ALLOWED_RELATION_TYPES
            ):
                continue
            key = (source, target, relation_type)
            if key in seen:
                continue
            seen.add(key)
            description = _sanitize_relation_description(
                connection.description,
                source,
                target,
                language_instruction,
            )
            filtered.append(
                RelationItem(
                    source=source,
                    target=target,
                    relation_type=relation_type,
                    description=description,
                )
            )
            if len(filtered) >= MAX_RELATION_CONNECTIONS:
                break

        return filtered

    def _fallback_relation_descriptions(
        self,
        card_paths: list[str],
        card_contents: list[str],
        language_instruction: str,
    ) -> list[RelationItem]:
        cards: list[dict[str, Any]] = []
        for card_path, card_content in zip(card_paths, card_contents):
            fm, _body = parse_frontmatter(card_content)
            concepts = [
                str(concept).strip()
                for concept in fm.get("concepts", [])
                if str(concept).strip()
            ]
            cards.append(
                {
                    "title": Path(card_path).stem,
                    "concepts": concepts,
                    "concept_keys": {concept.casefold() for concept in concepts},
                    "role": str(fm.get("graph_role") or "concept"),
                }
            )

        fallback: list[RelationItem] = []
        for left_index, left in enumerate(cards):
            for right in cards[left_index + 1:]:
                relation = self._build_rule_relation(left, right, language_instruction)
                if relation is None:
                    continue
                fallback.append(relation)
                if len(fallback) >= MAX_RELATION_CONNECTIONS:
                    return fallback
        return fallback

    def _build_rule_relation(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
        language_instruction: str,
    ) -> RelationItem | None:
        shared_keys = left["concept_keys"] & right["concept_keys"]
        if shared_keys:
            shared = [
                concept
                for concept in left["concepts"]
                if concept.casefold() in shared_keys
            ][:3]
            if _prefers_english(language_instruction):
                description = f"Both cards share concepts: {', '.join(shared)}."
            else:
                description = f"两张卡片共享概念：{'、'.join(shared)}。"
            return RelationItem(
                source=left["title"],
                target=right["title"],
                relation_type="comparison",
                description=description,
            )

        left_role = str(left["role"]).lower()
        right_role = str(right["role"]).lower()
        if left_role == "method" and right_role == "concept":
            return _rule_dependency_relation(left["title"], right["title"], language_instruction)
        if right_role == "method" and left_role == "concept":
            return _rule_dependency_relation(right["title"], left["title"], language_instruction)
        return None

    def _apply_relation_descriptions(
        self,
        vault_path: str,
        card_paths: list[str],
        card_contents: list[str],
        connections: list[RelationItem],
    ) -> int:
        if not connections:
            return 0

        # PIT-22: Only update target/new cards; never rewrite older cards.
        for i, (card_path, card_content) in enumerate(zip(card_paths, card_contents)):
            fm, body = parse_frontmatter(card_content)
            card_name = Path(card_path).stem
            related = [
                conn for conn in connections
                if conn.source == card_name or conn.target == card_name
            ]
            if not related:
                continue
            fm["relation_descriptions"] = [
                {
                    "source": r.source,
                    "target": r.target,
                    "relation_type": r.relation_type,
                    "description": r.description,
                }
                for r in related
            ]
            updated = serialize_frontmatter(fm, body)
            self.storage.write_file(str(Path(vault_path) / card_path), updated)
            card_contents[i] = updated

        return len(connections)

    def _step8_archive_and_index(
        self,
        instance_id: str,
        vault_path: str,
        source_path: str,
        source_content: str,
        card_paths: list[str],
        card_contents: list[str],
        map_path: str | None,
        result: IngestResult,
        now: str,
        job_id: str | None = None,
        classification: object | None = None,
    ) -> None:
        """Archive all files and update indexes.

        PIT-26: Removed first source note indexing to avoid duplicate indexing.
        The source note is indexed only once after frontmatter update.
        """
        # PIT-26: Skip first indexing - will be done after frontmatter update

        all_relations = []
        for card_path, card_content in zip(card_paths, card_contents):
            self.indexer.index_note(instance_id, card_path, card_content)
            fm, body = parse_frontmatter(card_content)
            relations = extract_all_relations(body, fm, card_path, vault_path, self.storage)
            all_relations.extend(relations)

            # Semantic index: update embedding for each card
            if self.semantic_index:
                try:
                    self.semantic_index.add_note(
                        instance_id,
                        card_path,
                        title=fm.get("title", Path(card_path).stem),
                        summary=body[:200] if body else "",
                        concepts=fm.get("concepts", []),
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to update semantic index for card %s (non-critical): %s",
                        card_path,
                        e,
                    )

        if map_path:
            map_content = self.storage.read_file(str(Path(vault_path) / map_path))
            self.indexer.index_note(instance_id, map_path, map_content)
            fm, body = parse_frontmatter(map_content)
            relations = extract_all_relations(body, fm, map_path, vault_path, self.storage)
            all_relations.extend(relations)

            # Semantic index: update embedding for map
            if self.semantic_index:
                try:
                    self.semantic_index.add_note(
                        instance_id,
                        map_path,
                        title=fm.get("title", Path(map_path).stem),
                        summary=body[:200] if body else "",
                        concepts=fm.get("concepts", []),
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to update semantic index for map %s (non-critical): %s",
                        map_path,
                        e,
                    )

        # Fix unresolved direct_link targets: resolve concept titles to card file paths
        concept_map = _build_concept_path_map(card_paths, card_contents)
        if concept_map:
            existing_paths = set()
            rows = self.db.execute(
                "SELECT file_path FROM notes WHERE instance_id = ?", (instance_id,)
            )
            for row in rows:
                existing_paths.add(row["file_path"])

            for rel in all_relations:
                if rel["rel_type"] == "direct_link" and rel["target_path"] not in existing_paths:
                    # PIT-24: concept_map now returns list, take first match
                    targets = concept_map.get(rel["target_path"].lower(), [])
                    resolved = next((t for t in targets if t in existing_paths), None)
                    if resolved:
                        rel["target_path"] = resolved

        self.indexer.index_relations(instance_id, all_relations)

        try:
            # PIT-25: Use incremental computation for write pipeline
            overlap_count = compute_concept_overlap_incremental(
                instance_id, card_paths, card_contents, self.db
            )
            if overlap_count:
                logger.info("Computed %d concept_overlap relations (incremental)", overlap_count)
        except Exception as e:
            logger.warning("Failed to compute concept_overlap (non-critical): %s", e)

        clear_wikilink_cache(vault_path)

        source_fm, source_body = parse_frontmatter(source_content)
        source_fm["extracted_cards"] = card_paths
        source_fm["card_count"] = len(card_paths)
        updated_source = serialize_frontmatter(source_fm, source_body)
        self.storage.write_file(str(Path(vault_path) / source_path), updated_source)
        self.indexer.index_note(instance_id, source_path, updated_source)

        # Semantic index: update embedding for source note
        if self.semantic_index:
            try:
                self.semantic_index.add_note(
                    instance_id,
                    source_path,
                    title=source_fm.get("doc_title", Path(source_path).stem),
                    summary=source_fm.get("doc_summary", ""),
                    concepts=source_fm.get("concepts", []),
                )
            except Exception as e:
                logger.warning(
                    "Failed to update semantic index for source %s (non-critical): %s",
                    source_path,
                    e,
                )
        if map_path:
            map_content = self.storage.read_file(str(Path(vault_path) / map_path))
            self.indexer.index_note(instance_id, map_path, map_content)

        refresh_instance_dictionary(instance_id, self.db)

        # Best-effort ontology candidate extraction (non-blocking)
        from app.pipeline.ontology_sync import sync_ontology_candidates
        try:
            sync_ontology_candidates(
                self.db, instance_id, card_paths, card_contents, classification,
            )
        except Exception:
            logger.warning("Ontology sync failed (non-blocking)", exc_info=True)

        if result.status != "partial_failed":
            result.status = "partial_failed" if result.has_blocking_warnings() else "success"
        self._record_job(instance_id, source_path, result, now, job_id)

    def _get_step_budget(self, step_name: str) -> int:
        return self.settings.llm_max_tokens

    def _build_source_note_context(self, content: str, structure: MarkdownStructure) -> str:
        tier = structure.size_tier.value
        if tier in ("tiny", "short"):
            return content
        if tier == "medium":
            return self._build_overview_context(
                content,
                structure,
                keywords=[h.title for h in structure.headings[:5]],
                intent_type="topic_scan",
                summary_chars=2000,
            )
        # long: 高/中密度全文 + 低密度摘要 + TOC
        keywords = [h.title for h in structure.headings[:5]]
        key_sections = extract_key_sections(content, structure, keywords, "topic_scan", max_sections=6)
        if tier == "xlong":
            summary = extract_summary(content, structure, max_chars=2000)
            context_text = f"TOC:\n{structure.toc}\n\nKEY SECTIONS:\n{key_sections}\n\nSUMMARY:\n{summary}"
            # PIT-09: Length pre-check for xlong documents
            # key_sections is a string, so truncate it progressively
            max_chars = int(self.settings.llm_context_window_chars * 0.8)
            while len(context_text) > max_chars and len(key_sections) > 500:
                # Remove last 500 chars from key_sections
                key_sections = key_sections[:-500]
                logger.debug("Context too long, truncated key_sections to %d chars", len(key_sections))
                context_text = f"TOC:\n{structure.toc}\n\nKEY SECTIONS:\n{key_sections}\n\nSUMMARY:\n{summary}"
            return context_text
        # long
        return f"TOC:\n{structure.toc}\n\nSELECTED SECTIONS:\n{key_sections}"

    def _build_locate_context(
        self,
        content: str,
        structure: MarkdownStructure,
        classification: DocClassification,
    ) -> str:
        tier = structure.size_tier.value
        keywords = classification.topics or [classification.domain, classification.kind]
        if tier in ("tiny", "short"):
            return content
        if tier == "medium":
            return self._build_overview_context(
                content,
                structure,
                keywords=keywords,
                intent_type="topic_scan",
                summary_chars=2000,
            )
        # long: 高/中密度全文 + 低密度摘要 + TOC
        key_sections = extract_key_sections(content, structure, keywords, "topic_scan", max_sections=6)
        if tier == "xlong":
            # xlong: 高密度全文 + 中密度摘要 + 低密度标题 + TOC
            summary = extract_summary(content, structure, max_chars=3000)
            toc_headings = "\n".join(f"- {h.title}" for h in structure.headings if h.level <= 3)
            return f"TOC:\n{structure.toc}\n\nKEY SECTIONS:\n{key_sections}\n\nSUMMARY:\n{summary}\n\nALL HEADINGS:\n{toc_headings}"
        # long
        if not key_sections:
            key_sections = extract_summary(content, structure, max_chars=4000)
        return f"TOC:\n{structure.toc}\n\nSELECTED CONTENT:\n{key_sections}"

    def _build_overview_context(
        self,
        content: str,
        structure: MarkdownStructure,
        keywords: list[str],
        intent_type: str,
        summary_chars: int,
    ) -> str:
        """Build a non-prefix context from TOC, selected sections, and visible summary."""
        key_sections = extract_key_sections(
            content,
            structure,
            keywords,
            intent_type,
            max_sections=5,
        )
        if not key_sections:
            key_sections = extract_summary(content, structure, max_chars=summary_chars)
        summary = extract_summary(content, structure, max_chars=summary_chars)
        toc = structure.toc or "\n".join(f"- {h.title}" for h in structure.headings)
        return f"TOC:\n{toc}\n\nKEY SECTIONS:\n{key_sections}\n\nSUMMARY:\n{summary}"

    def _truncate_source_note_fields(self, source_fm: dict) -> dict:
        """PIT-07: Improved frontmatter truncation with priority-based compression."""
        max_total = self.settings.source_note_fm_max_chars

        # Initial limits
        source_fm["doc_summary"] = truncate_with_marker(str(source_fm.get("doc_summary", "")), 2000)
        source_fm["extractable_knowledge_points"] = _truncate_list(
            source_fm.get("extractable_knowledge_points", []), 20
        )
        source_fm["concepts"] = _truncate_list(source_fm.get("concepts", []), 15)

        # Check if truncation is needed
        current_size = len(json.dumps(source_fm, ensure_ascii=False))
        if current_size <= max_total:
            return source_fm

        # PIT-07: Priority-based truncation
        # 1. First compress summary (preserve more knowledge points)
        summary = str(source_fm.get("doc_summary", ""))
        if len(summary) > 200:
            # Compress summary to 50% first
            target_len = max(len(summary) // 2, 200)
            source_fm["doc_summary"] = truncate_with_marker(summary, target_len)
            current_size = len(json.dumps(source_fm, ensure_ascii=False))

        # 2. Then remove knowledge points from the end
        while current_size > max_total:
            points = source_fm.get("extractable_knowledge_points", [])
            if points:
                source_fm["extractable_knowledge_points"] = points[:-1]
                current_size = len(json.dumps(source_fm, ensure_ascii=False))
                continue

            # 3. Further compress summary if still over limit
            summary = str(source_fm.get("doc_summary", ""))
            if len(summary) > 200:
                source_fm["doc_summary"] = truncate_with_marker(summary, max(len(summary) - 200, 200))
                current_size = len(json.dumps(source_fm, ensure_ascii=False))
                continue

            # 4. Reduce concepts as last resort
            concepts = source_fm.get("concepts", [])
            if concepts:
                source_fm["concepts"] = concepts[:-1]
                current_size = len(json.dumps(source_fm, ensure_ascii=False))
                continue

            break

        return source_fm

    def _validate_card_quality(self, card: CardOutput) -> tuple[list[str], list[str]]:
        """Validate card quality. Returns (errors, warnings).

        Errors trigger retry with expanded context; warnings are logged only.
        PIT-15: Enhanced validation with more field checks.
        """
        return validate_card_output(card)

    def _collect_existing_card_names(
        self,
        vault_path: str,
        card_paths: list[str],
        points: list[KnowledgePointOutput],
    ) -> set[str]:
        names: set[str] = set()
        try:
            vault_card_files = self.storage.list_files(str(Path(vault_path) / CARD_DIR), "*.md")
            names.update(Path(f).stem for f in vault_card_files)
        except Exception:
            pass
        names.update(Path(p).stem for p in card_paths)
        names.update(p.card_title for p in points if p.card_title)
        return names

    def _build_card_summaries(self, card_paths: list[str], card_contents: list[str]) -> list[dict]:
        summaries = []
        for path, content in zip(card_paths, card_contents):
            fm, body = parse_frontmatter(content)
            title = Path(path).stem
            for line in body.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            summaries.append(
                {
                    "path": path,
                    "title": title,
                    "concepts": fm.get("concepts", []),
                    "summary": _extract_card_summary_preview(body, 200),
                }
            )
        return summaries


def _para_range_for_section(section_id: int | None, structure: MarkdownStructure) -> list[int]:
    """Derive paragraph index range for a given section_id from structure."""
    if section_id is None or not structure.paragraphs:
        return [0, 0]
    indices = [i for i, p in enumerate(structure.paragraphs) if p.section_id == section_id]
    if not indices:
        return [0, 0]
    return [indices[0], indices[-1]]


def _safe_name(value: str) -> str:
    """PIT-06: Enhanced filename sanitization for all platforms."""
    # Clean all platform-illegal characters
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value or "untitled")
    # Remove leading/trailing dots and spaces
    name = name.strip('. ')
    # Limit length to 200 characters
    return name[:200] if name else "untitled"


def _finish_reason_value(value: Any) -> str:
    """Return provider finish_reason as a plain lowercase string."""
    if value is None:
        return ""
    return str(getattr(value, "value", value)).lower()


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _usage_counts(usage: Any) -> dict[str, int]:
    prompt_tokens = _usage_value(usage, "request_tokens", "input_tokens", "prompt_tokens")
    completion_tokens = _usage_value(
        usage,
        "response_tokens",
        "output_tokens",
        "completion_tokens",
    )
    total_tokens = _usage_value(usage, "total_tokens")
    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _usage_value(usage: Any, *names: str) -> int:
    for name in names:
        value = getattr(usage, name, None)
        if isinstance(value, int):
            return value
    return 0


def _truncate_list(values: list, limit: int) -> list:
    seen = []
    for value in values or []:
        if value and value not in seen:
            seen.append(value)
        if len(seen) >= limit:
            break
    return seen


def _strip_free_text_wikilinks(value: Any) -> str:
    """Render LLM free-text wikilinks as plain text to avoid unresolved links."""
    text = str(value or "")
    return FREE_TEXT_WIKILINK_RE.sub(
        lambda match: (match.group(2) or match.group(1)).strip(),
        text,
    )


def _prefers_english(language_instruction: str) -> bool:
    return "英文" in language_instruction or "English" in language_instruction


def _card_extra_section_titles(language_instruction: str) -> dict[str, str]:
    if _prefers_english(language_instruction):
        return CARD_EXTRA_SECTION_TITLES["en"]
    return CARD_EXTRA_SECTION_TITLES["zh"]


def _map_section_titles(language_instruction: str) -> dict[str, str]:
    if _prefers_english(language_instruction):
        return MAP_SECTION_TITLES["en"]
    return MAP_SECTION_TITLES["zh"]


def _extract_first_section_preview(body: str, headings: list[str], max_chars: int) -> str:
    for heading in headings:
        preview = _extract_section_preview_if_present(body, heading, max_chars)
        if preview:
            return preview
    return ""


def _extract_card_summary_preview(body: str, max_chars: int) -> str:
    lines = body.splitlines()
    after_title = False
    summary_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            after_title = True
            continue
        if not after_title or not stripped:
            continue
        if stripped.startswith("## "):
            break
        summary_lines.append(stripped)
    summary = " ".join(summary_lines).strip()
    if summary:
        return truncate_with_marker(summary, max_chars)
    return _extract_section_preview(body, "Summary", max_chars)


def _normalize_relation_type(value: Any) -> str:
    return _strip_free_text_wikilinks(value).strip().lower()


def _sanitize_relation_description(
    value: Any,
    source: str,
    target: str,
    language_instruction: str,
) -> str:
    description = truncate_with_marker(_strip_free_text_wikilinks(value).strip(), 180)
    if description:
        return description
    if _prefers_english(language_instruction):
        return f"{source} is related to {target}."
    return f"{source} 与 {target} 存在知识关联。"


def _rule_dependency_relation(
    method_title: str,
    concept_title: str,
    language_instruction: str,
) -> RelationItem:
    if _prefers_english(language_instruction):
        description = "The method card depends on the concept card as background."
    else:
        description = "方法卡片依赖概念卡片作为背景。"
    return RelationItem(
        source=method_title,
        target=concept_title,
        relation_type="dependency",
        description=description,
    )


def _canonical_source_material(
    source_path: str,
    source_output: SourceNoteOutput,
    source_materials: list[dict],
) -> dict:
    path = _canonical_vault_path(source_path)
    title = _clean_map_text(getattr(source_output, "title", "")) or Path(path).stem
    reason = "source material"
    first_material = next((item for item in source_materials or [] if isinstance(item, dict)), None)
    if first_material:
        reason = _clean_map_text(first_material.get("reason")) or reason
    return {"title": title, "path": path, "reason": reason}


def _canonicalize_card_references(items: list[dict], card_summaries: list[dict]) -> list[dict]:
    card_index = _build_card_reference_index(card_summaries)
    canonical: list[dict] = []
    for value in items or []:
        item = dict(value) if isinstance(value, dict) else {"title": str(value)}
        raw_card = item.get("card") or item.get("path") or ""
        raw_title = item.get("title") or item.get("name") or ""
        matched = _match_card_reference(raw_card, raw_title, card_index)
        item.pop("path", None)
        if matched:
            item["card"] = matched["path"]
            if not _clean_map_text(item.get("title")):
                item["title"] = matched["title"]
        else:
            item.pop("card", None)
        canonical.append(item)
    return canonical


def _canonicalize_linked_maps(
    linked_maps: list[dict],
    vault_path: str,
    storage: StorageBackend,
) -> list[dict]:
    canonical: list[dict] = []
    for value in linked_maps or []:
        item = dict(value) if isinstance(value, dict) else {"title": str(value)}
        path = _canonical_vault_path(item.get("path") or "")
        item.pop("path", None)
        if path and storage.exists(str(Path(vault_path) / path)):
            item["path"] = path
        if any(_clean_map_text(item.get(key)) for key in ("title", "reason", "path")):
            canonical.append(item)
    return canonical


def _build_card_reference_index(card_summaries: list[dict]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for card in card_summaries:
        path = _canonical_vault_path(card.get("path") or "")
        if not path:
            continue
        title = _clean_map_text(card.get("title")) or Path(path).stem
        entry = {"path": path, "title": title}
        for key in _reference_lookup_keys(path, title):
            index.setdefault(key, entry)
    return index


def _match_card_reference(
    raw_card: Any,
    raw_title: Any,
    card_index: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    for key in _reference_lookup_keys(raw_card, raw_title):
        if key in card_index:
            return card_index[key]
    return None


def _reference_lookup_keys(*values: Any) -> list[str]:
    keys: list[str] = []
    for value in values:
        text = _canonical_vault_path(value)
        if not text:
            continue
        candidates = [text, Path(text).stem]
        if text.endswith(".md"):
            candidates.append(text[:-3])
        for candidate in candidates:
            key = candidate.casefold()
            if key and key not in keys:
                keys.append(key)
    return keys


def _canonical_vault_path(value: Any) -> str:
    return normalize_vault_path(str(value or "")).strip("/")


def _format_note_link(path: str, title: str) -> str:
    target = _canonical_vault_path(path)
    display = _clean_map_text(title) or Path(target).stem
    if not target:
        return display
    if display and display != target:
        return f"[[{target}|{display}]]"
    return f"[[{target}]]"


def _clean_map_text(value: Any) -> str:
    return str(value or "").replace("\n", " ").replace("|", "-").replace("]", "").strip()


def _build_concept_path_map(
    card_paths: list[str], card_contents: list[str]
) -> dict[str, list[str]]:
    """Build a mapping from concept names (lowercase) to card file paths.

    Used to resolve wikilinks that reference concept titles rather than file stems.
    PIT-24: Changed to dict[str, list[str]] to handle duplicate concepts from multiple cards.
    """
    from collections import defaultdict
    concept_map: dict[str, list[str]] = defaultdict(list)
    for card_path, card_content in zip(card_paths, card_contents):
        fm, _ = parse_frontmatter(card_content)
        concepts = fm.get("concepts", [])
        for concept in concepts:
            if concept:
                key = concept.lower()
                if card_path not in concept_map[key]:
                    concept_map[key].append(card_path)
    return dict(concept_map)


def _extract_section_preview(body: str, heading: str, max_chars: int) -> str:
    preview = _extract_section_preview_if_present(body, heading, max_chars)
    if preview:
        return preview
    return truncate_with_marker(body, max_chars)


def _extract_section_preview_if_present(body: str, heading: str, max_chars: int) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(body)
    if not match:
        return ""
    rest = body[match.end():]
    next_heading = rest.find("\n## ")
    section = rest[:next_heading] if next_heading >= 0 else rest
    return truncate_with_marker(section.strip(), max_chars)


def _build_map_body(
    output: MapOutput,
    core_concepts: list[dict],
    reading_path: list[dict],
    source_materials: list[dict],
    linked_maps: list[dict],
    language_instruction: str,
) -> str:
    titles = _map_section_titles(language_instruction)
    body_parts = [
        f"# {output.title}",
        "",
        f"## {titles['topic_overview']}",
        "",
        output.topic_overview,
        "",
        f"## {titles['core_concepts']}",
        "",
    ]
    for concept in core_concepts:
        title = concept.get("title") or concept.get("name") or concept.get("card", "")
        role = concept.get("role", "normal")
        card = concept.get("card") or concept.get("path") or ""
        summary = concept.get("summary") or concept.get("description") or ""
        link = _format_note_link(card, title) if card else _clean_map_text(title)
        body_parts.append(f"- {link} ({role}) {summary}".strip())

    body_parts.extend(["", f"## {titles['reading_path']}", ""])
    for item in reading_path:
        order = item.get("order", "")
        title = item.get("title") or item.get("card") or item.get("path", "")
        card = item.get("card") or item.get("path") or ""
        reason = item.get("reason", "")
        link = _format_note_link(card, title) if card else _clean_map_text(title)
        prefix = f"{order}. " if order else "- "
        body_parts.append(f"{prefix}{link} {reason}".strip())

    body_parts.extend(["", f"## {titles['key_relations']}", ""])
    if output.key_relations:
        for rel in output.key_relations:
            left = rel.get("from") or rel.get("source") or ""
            relation = rel.get("relation") or rel.get("type") or ""
            right = rel.get("to") or rel.get("target") or ""
            desc = rel.get("description") or ""
            body_parts.append(f"- {left} --{relation}--> {right} {desc}".strip())
    elif output.relationship_context:
        body_parts.append(output.relationship_context)

    body_parts.extend(["", f"## {titles['source_materials']}", ""])
    for source in source_materials:
        path = source.get("path") or source.get("source") or ""
        title = source.get("title") or Path(path).stem
        reason = source.get("reason", "")
        link = _format_note_link(path, title) if path else _clean_map_text(title)
        body_parts.append(f"- {link} {reason}".strip())

    body_parts.extend(["", f"## {titles['linked_maps']}", ""])
    for linked_map in linked_maps:
        path = linked_map.get("path") or ""
        title = linked_map.get("title") or Path(path).stem
        reason = linked_map.get("reason", "")
        link = _format_note_link(path, title) if path else _clean_map_text(title)
        body_parts.append(f"- {link} {reason}".strip())
    return "\n".join(body_parts)
