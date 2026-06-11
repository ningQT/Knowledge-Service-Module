"""pydantic-ai output validators for write-pipeline agents."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic_ai import Agent, ModelRetry, RunContext

from app.llm.agents import StepDeps
from app.llm.schemas import (
    MAX_CARD_CONCEPTS,
    MAX_CARD_WIKILINKS,
    STEP2_MAX_CANDIDATE_CARDS,
    CardOutput,
    KnowledgeLocateResult,
    PathDecision,
)

_ILLEGAL_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def clean_card_name(value: str) -> str:
    """Normalize LLM-proposed card names before downstream file creation."""
    return _ILLEGAL_FILENAME_RE.sub("_", value or "").strip(". ")


def register_step2_validators(agent: Agent) -> Agent:
    @agent.output_validator
    def validate_path_decision(
        ctx: RunContext[StepDeps],
        output: PathDecision,
    ) -> PathDecision:
        cleaned = []
        for card in output.candidate_cards:
            name = clean_card_name(card)
            if name and name not in cleaned:
                cleaned.append(name)
        output.candidate_cards = cleaned[:STEP2_MAX_CANDIDATE_CARDS]
        if not output.source_name:
            raise ModelRetry("source_name is required.")
        return output

    return agent


def register_step4_locate_validators(agent: Agent) -> Agent:
    @agent.output_validator
    def validate_locate_result(
        ctx: RunContext[StepDeps],
        output: KnowledgeLocateResult,
    ) -> KnowledgeLocateResult:
        valid_ids = set(ctx.deps.section_id_map)
        if not valid_ids:
            return output

        invalid_ids = [
            pt.section_id
            for pt in output.knowledge_points
            if pt.section_id is not None and pt.section_id not in valid_ids
        ]
        if invalid_ids:
            preview = ", ".join(str(i) for i in sorted(set(invalid_ids))[:8])
            allowed = ", ".join(str(i) for i in sorted(valid_ids)[:30])
            raise ModelRetry(
                f"Invalid section_id values: {preview}. Use only these integer section_id values: {allowed}."
            )

        for point in output.knowledge_points:
            if point.section_id is not None and not point.section_title:
                point.section_title = ctx.deps.section_id_map.get(point.section_id)
        return output

    return agent


def validate_card_output(card: CardOutput) -> tuple[list[str], list[str]]:
    """Validate generated card quality. Errors should trigger model retry."""
    errors: list[str] = []
    warnings: list[str] = []

    if not card.title:
        errors.append("title is required")
    if not card.summary:
        errors.append("summary is required")
    elif len(card.summary.strip()) < 20:
        errors.append("summary is shorter than 20 characters")
    if len(card.sections) < 2:
        errors.append("sections must contain at least 2 items")
    if len(card.sections) > 6:
        warnings.append("sections has more than 6 items")

    has_substantial_section = False
    for index, section in enumerate(card.sections, start=1):
        if not section.heading.strip():
            errors.append(f"sections[{index}].heading is required")
        content = section.content.strip()
        if not content:
            errors.append(f"sections[{index}].content is required")
        if len(content) >= 30:
            has_substantial_section = True
    if card.sections and not has_substantial_section:
        errors.append("at least one section content must be 30 characters or longer")

    if not card.concepts:
        warnings.append("concepts is empty")
    elif len(card.concepts) > MAX_CARD_CONCEPTS:
        warnings.append(f"concepts has more than {MAX_CARD_CONCEPTS} items")
    if not card.relations:
        warnings.append("relations is empty")
    if not card.sources_text:
        warnings.append("sources_text is empty")

    return errors, warnings


def register_step5_card_validators(agent: Agent) -> Agent:
    @agent.output_validator
    def validate_card(
        ctx: RunContext[StepDeps],
        output: CardOutput,
    ) -> CardOutput:
        output.concepts = output.concepts[:MAX_CARD_CONCEPTS]
        output.wikilinks = output.wikilinks[:MAX_CARD_WIKILINKS]
        errors, _warnings = validate_card_output(output)
        if errors:
            raise ModelRetry("; ".join(errors))

        if output.wikilinks and ctx.deps.existing_card_names:
            output.wikilinks = [
                link
                for link in output.wikilinks[:MAX_CARD_WIKILINKS]
                if link in ctx.deps.existing_card_names or Path(link).stem in ctx.deps.existing_card_names
            ]

        if ctx.deps.point_role:
            output.graph_role = ctx.deps.point_role
        return output

    return agent
