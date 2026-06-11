"""LLM client facade backed by the model provider registry."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

from app.config import Settings
from app.llm.providers import get_provider_registry
from app.llm.prompts.common import RETURN_STRICT_JSON_ONLY
from app.llm.schemas import LLMResult, TokenUsage
from app.observability import log_event, next_llm_call_id

logger = logging.getLogger(__name__)


class LLMClient:
    """Provider-agnostic LLM client used by KSM pipelines."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.provider_id = settings.llm_provider
        self.model = settings.llm_model
        self.temperature = settings.llm_temperature
        self.max_tokens = settings.llm_max_tokens

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        call_name: str = "chat_completion",
    ) -> LLMResult:
        """Send a chat completion request through the configured provider."""
        llm_call_id = next_llm_call_id()
        started = time.perf_counter()
        effective_max_tokens = max_tokens or self.max_tokens
        log_event(
            logger,
            "llm.call.start",
            llm_call_id=llm_call_id,
            call_name=call_name,
            provider=self.provider_id,
            model=self.model,
            max_tokens=effective_max_tokens,
        )
        attempts = 0
        try:
            instructions, prompt = _messages_to_agent_parts(messages)
            if response_format and response_format.get("type") == "json_object":
                instructions = "\n\n".join(
                    part for part in [instructions, RETURN_STRICT_JSON_ONLY] if part
                )

            model = get_provider_registry().build_chat_model(self.settings)
            agent = Agent(
                model,
                output_type=str,
                instructions=instructions or None,
                model_settings=ModelSettings(
                    max_tokens=effective_max_tokens,
                    temperature=temperature if temperature is not None else self.temperature,
                ),
            )
            for attempt in range(2):
                attempts = attempt + 1
                try:
                    run = agent.run_sync(prompt)
                    result = LLMResult(
                        content=run.output,
                        finish_reason=_finish_reason(run),
                        usage=_token_usage(run.usage()),
                        model=self.model,
                        id="",
                    )
                    log_event(
                        logger,
                        "llm.call.done",
                        llm_call_id=llm_call_id,
                        call_name=call_name,
                        provider=self.provider_id,
                        model=result.model or self.model,
                        finish_reason=result.finish_reason,
                        prompt_tokens=result.usage.prompt_tokens,
                        completion_tokens=result.usage.completion_tokens,
                        total_tokens=result.usage.total_tokens,
                        usage_missing=result.usage.total_tokens == 0,
                        attempts=attempts,
                        duration_ms=_duration_ms(started),
                    )
                    return result
                except Exception as exc:
                    logger.warning("LLM call attempt %s failed: %s", attempt + 1, exc)
                    if attempt == 1:
                        raise
        except Exception as exc:
            log_event(
                logger,
                "llm.call.error",
                level=logging.ERROR,
                llm_call_id=llm_call_id,
                call_name=call_name,
                provider=self.provider_id,
                model=self.model,
                attempts=attempts,
                duration_ms=_duration_ms(started),
                error_type=exc.__class__.__name__,
                exc_info=True,
            )
            raise

        return LLMResult(content="")  # pragma: no cover

    def generate_json(
        self,
        prompt: str,
        system_prompt: str = RETURN_STRICT_JSON_ONLY,
    ) -> dict:
        """Generate a JSON response from the LLM."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        result = self.chat_completion(
            messages,
            response_format={"type": "json_object"},
            call_name="generate_json",
        )
        return json.loads(result.content)


def _messages_to_agent_parts(messages: list[dict[str, str]]) -> tuple[str, str]:
    system_parts: list[str] = []
    prompt_parts: list[str] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
        elif role == "user":
            prompt_parts.append(content)
        else:
            prompt_parts.append(f"{role}: {content}")
    return "\n\n".join(system_parts), "\n\n".join(prompt_parts)


def _finish_reason(run: Any) -> str:
    response = getattr(run, "response", None)
    finish_reason = getattr(response, "finish_reason", None)
    if finish_reason:
        return str(finish_reason)
    return "stop"


def _token_usage(usage: Any) -> TokenUsage:
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
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def _usage_value(usage: Any, *names: str) -> int:
    for name in names:
        value = getattr(usage, name, None)
        if isinstance(value, int):
            return value
    return 0


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
