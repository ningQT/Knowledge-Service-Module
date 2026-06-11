"""pydantic-ai agents for structured write-pipeline LLM calls."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

from app.config import Settings
from app.llm.schemas import (
    CardFilterResult,
    CardOutput,
    DocClassification,
    KnowledgeLocateResult,
    MapOutput,
    PathDecision,
    RelationDescOutput,
    SourceNoteOutput,
)
from app.llm.providers import get_provider_registry
from app.llm.prompts.agents import (
    STEP1_CLASSIFY_INSTRUCTIONS,
    STEP2_PATH_INSTRUCTIONS,
    STEP3_SOURCE_INSTRUCTIONS,
    STEP4_FILTER_INSTRUCTIONS,
    STEP4_LOCATE_INSTRUCTIONS,
    STEP5_CARD_INSTRUCTIONS,
    STEP6_MAP_INSTRUCTIONS,
    STEP7_RELATION_INSTRUCTIONS,
)


@dataclass
class StepDeps:
    """Runtime context used by pydantic-ai output validators."""

    settings: Settings
    section_id_map: dict[int, str] = field(default_factory=dict)
    existing_card_names: set[str] = field(default_factory=set)
    point_role: str = "concept"


def _agent(
    settings: Settings,
    output_type: type,
    instructions: str,
    *,
    output_retries: int = 2,
) -> Agent:
    return Agent(
        get_provider_registry().build_chat_model(settings),
        output_type=output_type,
        deps_type=StepDeps,
        instructions=instructions,
        model_settings=ModelSettings(
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        ),
        retries=1,
        output_retries=output_retries,
    )


def create_step1_classify_agent(settings: Settings) -> Agent:
    return _agent(
        settings,
        DocClassification,
        STEP1_CLASSIFY_INSTRUCTIONS,
    )


def create_step2_path_agent(settings: Settings) -> Agent:
    return _agent(
        settings,
        PathDecision,
        STEP2_PATH_INSTRUCTIONS,
    )


def create_step3_source_agent(settings: Settings) -> Agent:
    return _agent(
        settings,
        SourceNoteOutput,
        STEP3_SOURCE_INSTRUCTIONS,
    )


def create_step4_filter_agent(settings: Settings) -> Agent:
    return _agent(
        settings,
        CardFilterResult,
        STEP4_FILTER_INSTRUCTIONS,
    )


def create_step4_locate_agent(settings: Settings) -> Agent:
    return _agent(
        settings,
        KnowledgeLocateResult,
        STEP4_LOCATE_INSTRUCTIONS,
        output_retries=3,
    )


def create_step5_card_agent(settings: Settings) -> Agent:
    return _agent(
        settings,
        CardOutput,
        STEP5_CARD_INSTRUCTIONS,
        output_retries=2,
    )


def create_step6_map_agent(settings: Settings) -> Agent:
    return _agent(
        settings,
        MapOutput,
        STEP6_MAP_INSTRUCTIONS,
    )


def create_step7_relation_agent(settings: Settings) -> Agent:
    return _agent(
        settings,
        RelationDescOutput,
        STEP7_RELATION_INSTRUCTIONS,
    )
