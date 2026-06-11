"""API routes for model provider settings management."""

from __future__ import annotations

import json
import logging
import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_db, require_admin_context, reset_llm_client
from app.api.models import (
    LLMSettingsRequest,
    LLMSettingsResponse,
    LLMSettingsResetResponse,
    LLMSettingsUpdateResponse,
    LLMTestRequest,
    LLMTestResponse,
)
from app.config import get_effective_settings, reload_effective_settings
from app.llm.client import LLMClient
from app.llm.providers import LLMNotConfiguredError, UnsupportedProviderCapabilityError, get_provider_registry
from app.llm.prompts.settings import LLM_HEALTH_CHECK_SYSTEM_PROMPT
from app.observability import log_event
from app.security.url_validation import validate_llm_base_url

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/settings",
    tags=["settings"],
    dependencies=[Depends(require_admin_context)],
)

_LLM_FIELDS = ["provider", "base_url", "api_key", "model", "temperature", "max_tokens"]


def _mask_api_key(key: str) -> str:
    """Mask API key for display: sk-****xxxx."""
    if not key:
        return ""
    if len(key) < 8:
        return "****"
    return f"{key[:3]}****{key[-4:]}"


def _provider_options() -> list[dict]:
    return [descriptor.public_dict() for descriptor in get_provider_registry().list_providers()]


def _build_settings_response(effective) -> LLMSettingsResponse:
    registry = get_provider_registry()
    provider_id = effective.llm_provider or ""
    provider_display_name: str | None = None
    if provider_id:
        try:
            provider_display_name = registry.get_provider(provider_id).descriptor.display_name
        except UnsupportedProviderCapabilityError:
            provider_display_name = None

    try:
        missing_fields = registry.missing_fields(effective)
    except UnsupportedProviderCapabilityError:
        missing_fields = ["provider"]

    return LLMSettingsResponse(
        provider=provider_id,
        provider_display_name=provider_display_name,
        base_url=effective.llm_base_url or "",
        api_key_masked=_mask_api_key(effective.llm_api_key),
        model=effective.llm_model or "",
        temperature=effective.llm_temperature,
        max_tokens=effective.llm_max_tokens,
        configured=not missing_fields,
        missing_fields=missing_fields,
        provider_options=_provider_options(),
    )


def _clean_update_value(field: str, value):
    if isinstance(value, str):
        value = value.strip()
    if field == "provider" and value:
        get_provider_registry().get_provider(value)
    if field == "base_url" and value:
        effective = get_effective_settings(get_db())
        value = validate_llm_base_url(
            value,
            require_https=effective.require_https_llm_base_url,
            ssrf_protection=effective.llm_ssrf_protection,
        )
    return value


@router.get("/llm", response_model=LLMSettingsResponse)
async def get_llm_settings():
    """Get current model provider configuration."""
    return _build_settings_response(get_effective_settings(get_db()))


@router.put("/llm", response_model=LLMSettingsUpdateResponse)
async def update_llm_settings(req: LLMSettingsRequest):
    """Update model provider configuration (persist to DB + hot-reload)."""
    started = time.perf_counter()
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Request body must contain at least one field")
    log_event(
        logger,
        "settings.llm.update.start",
        updated_fields=sorted(updates),
    )

    unknown = sorted(set(updates) - set(_LLM_FIELDS))
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unsupported LLM settings: {', '.join(unknown)}")

    db = get_db()
    for field, value in updates.items():
        try:
            cleaned = _clean_update_value(field, value)
        except (UnsupportedProviderCapabilityError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.set_setting(f"llm.{field}", json.dumps(cleaned))

    reload_effective_settings(db)
    reset_llm_client()
    settings_resp = _build_settings_response(get_effective_settings(db))
    log_event(
        logger,
        "settings.llm.update.done",
        updated_fields=sorted(updates),
        configured=settings_resp.configured,
        provider=settings_resp.provider,
        model=settings_resp.model,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return LLMSettingsUpdateResponse(updated=True, settings=settings_resp)


@router.delete("/llm", response_model=LLMSettingsResetResponse)
async def reset_llm_settings():
    """Clear console-managed model provider configuration."""
    started = time.perf_counter()
    log_event(logger, "settings.llm.reset.start")
    db = get_db()
    db.delete_settings("llm.")
    reload_effective_settings(db)
    reset_llm_client()
    log_event(
        logger,
        "settings.llm.reset.done",
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return LLMSettingsResetResponse()


@router.post("/llm/test", response_model=LLMTestResponse)
async def test_llm_connection(req: LLMTestRequest | None = None):
    """Test model provider connectivity with current or provided config."""
    effective = get_effective_settings(get_db())
    updates = req.model_dump(exclude_none=True) if req else {}
    if "base_url" in updates and updates["base_url"]:
        try:
            updates["base_url"] = validate_llm_base_url(
                updates["base_url"],
                require_https=effective.require_https_llm_base_url,
                ssrf_protection=effective.llm_ssrf_protection,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    settings = effective.model_copy(update={f"llm_{field}": value for field, value in updates.items()})
    model_name = settings.llm_model or ""
    log_event(
        logger,
        "settings.llm.test.start",
        provider=settings.llm_provider,
        model=model_name,
        override_fields=sorted(updates),
    )

    start = time.monotonic()
    try:
        result = await asyncio.to_thread(
            LLMClient(settings).chat_completion,
            [
                {"role": "system", "content": LLM_HEALTH_CHECK_SYSTEM_PROMPT},
                {"role": "user", "content": "Hi"},
            ],
            max_tokens=min(settings.llm_max_tokens or 64, 64),
            call_name="settings.llm_test",
        )
        latency = int((time.monotonic() - start) * 1000)
        log_event(
            logger,
            "settings.llm.test.done",
            success=True,
            provider=settings.llm_provider,
            model=result.model or model_name,
            duration_ms=latency,
        )
        return LLMTestResponse(success=True, model=result.model or model_name, latency_ms=latency)
    except (LLMNotConfiguredError, UnsupportedProviderCapabilityError) as exc:
        latency = int((time.monotonic() - start) * 1000)
        log_event(
            logger,
            "settings.llm.test.done",
            level=logging.WARNING,
            success=False,
            provider=settings.llm_provider,
            model=model_name,
            duration_ms=latency,
            error_type=exc.__class__.__name__,
        )
        return LLMTestResponse(success=False, model=model_name, latency_ms=latency, error=str(exc))
    except Exception as exc:
        latency = int((time.monotonic() - start) * 1000)
        logger.warning("Unexpected error testing LLM connection: %s", exc)
        log_event(
            logger,
            "settings.llm.test.done",
            level=logging.WARNING,
            success=False,
            provider=settings.llm_provider,
            model=model_name,
            duration_ms=latency,
            error_type=exc.__class__.__name__,
        )
        return LLMTestResponse(
            success=False,
            model=model_name,
            latency_ms=latency,
            error=f"{type(exc).__name__}: {str(exc)[:500]}",
        )
