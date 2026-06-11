"""FastAPI dependency injection — provides service instances."""

import logging
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, Request

from app.config import get_effective_settings, get_settings
from app.core.answer_service import AnswerService
from app.core.auth_service import AuthContext, AuthService
from app.core.ingest_service import IngestService
from app.core.instance_service import InstanceService
from app.core.note_service import NoteService
from app.core.ontology_service import OntologyService
from app.core.search_lexicon_service import SearchLexiconService
from app.core.search_service import SearchService
from app.core.sync_service import SyncService
from app.llm.client import LLMClient
from app.observability import log_event
from app.storage.indexer import Indexer
from app.storage.local_backend import LocalStorageBackend
from app.storage.sqlite_backend import SQLiteBackend
from app.template.registry import TemplateRegistry

AUTH_COOKIE_NAME = "ksm_admin_session"
logger = logging.getLogger(__name__)


@lru_cache
def get_db() -> SQLiteBackend:
    settings = get_settings()
    db_path = f"{settings.data_dir}/ksm.db"
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = SQLiteBackend(
        db_path,
        backup_dir=settings.db_backup_dir,
        backup_before_migration=settings.backup_before_migration,
    )
    db.init_schema()
    return db


@lru_cache
def get_storage() -> LocalStorageBackend:
    settings = get_settings()
    return LocalStorageBackend(settings.data_dir)


@lru_cache
def get_indexer() -> Indexer:
    return Indexer(get_db())


@lru_cache
def get_llm_client() -> LLMClient:
    settings = get_effective_settings()
    return LLMClient(settings)


@lru_cache
def get_template_registry() -> TemplateRegistry:
    settings = get_settings()
    registry = TemplateRegistry(settings.template_dir)
    registry.load_templates()
    return registry


def get_instance_service() -> InstanceService:
    settings = get_settings()
    return InstanceService(get_db(), get_storage(), get_template_registry(), settings)


def get_ingest_service() -> IngestService:
    settings = get_effective_settings()
    return IngestService(get_db(), get_storage(), get_llm_client(), settings, indexer=get_indexer())


def get_ingest_service_for_background() -> tuple[IngestService, SQLiteBackend]:
    """为后台线程创建独立的 IngestService 实例（不复用缓存的 DB 连接）。

    设计文档 §885: 后台线程创建独立的 SQLiteBackend 实例，不复用 get_db() 的 @lru_cache 单例。
    返回 (service, db) 元组，调用方需在完成后调用 db.close()。
    """
    settings = get_effective_settings()
    db_path = f"{settings.data_dir}/ksm.db"
    db = SQLiteBackend(
        db_path,
        backup_dir=settings.db_backup_dir,
        backup_before_migration=settings.backup_before_migration,
    )
    db.init_schema()
    storage = LocalStorageBackend(settings.data_dir)
    llm = get_llm_client()
    indexer = Indexer(db)
    svc = IngestService(db, storage, llm, settings, indexer=indexer)
    return svc, db


def get_answer_service() -> AnswerService:
    settings = get_effective_settings()
    return AnswerService(get_db(), get_storage(), get_llm_client(), settings)


def get_answer_service_for_background() -> tuple[AnswerService, SQLiteBackend]:
    settings = get_effective_settings()
    db_path = f"{settings.data_dir}/ksm.db"
    db = SQLiteBackend(
        db_path,
        backup_dir=settings.db_backup_dir,
        backup_before_migration=settings.backup_before_migration,
    )
    db.init_schema()
    storage = LocalStorageBackend(settings.data_dir)
    svc = AnswerService(db, storage, get_llm_client(), settings)
    return svc, db


def get_search_service() -> SearchService:
    settings = get_settings()
    return SearchService(get_db(), get_storage(), settings)


def get_sync_service() -> SyncService:
    return SyncService(get_db(), get_storage(), get_indexer())


def get_note_service() -> NoteService:
    return NoteService(get_db(), get_storage())


def get_search_lexicon_service() -> SearchLexiconService:
    return SearchLexiconService(get_db())


def get_auth_service() -> AuthService:
    return AuthService(get_db())


def get_ontology_service() -> OntologyService:
    from app.pipeline.query_dictionary import invalidate_query_caches
    return OntologyService(get_db(), on_change=invalidate_query_caches)


async def get_optional_auth_context(request: Request) -> AuthContext | None:
    """Return the authenticated context if a valid cookie or API key is present."""
    svc = get_auth_service()
    session_token = request.cookies.get(AUTH_COOKIE_NAME)
    if session_token:
        context = svc.get_session_context(session_token)
        if context:
            log_event(
                logger,
                "auth.success",
                auth_kind=context.kind,
                scope=context.scope,
                is_admin=context.is_admin,
            )
            return context

    api_key = _extract_bearer_token(request)
    if api_key:
        context = svc.get_api_key_context(api_key)
        if context:
            log_event(
                logger,
                "auth.success",
                auth_kind=context.kind,
                scope=context.scope,
                is_admin=context.is_admin,
                instance_count=len(context.instance_ids),
            )
        return context

    return None


async def require_auth_context(request: Request) -> AuthContext:
    """Require either an administrator session or a valid API key."""
    context = await get_optional_auth_context(request)
    if context:
        return context

    if _extract_bearer_token(request):
        log_event(logger, "auth.denied", reason="invalid_api_key")
        raise HTTPException(status_code=401, detail="Invalid API key")
    if not get_auth_service().has_admin():
        log_event(logger, "auth.denied", reason="admin_setup_required")
        raise HTTPException(status_code=403, detail="Admin setup required")
    log_event(logger, "auth.denied", reason="authentication_required")
    raise HTTPException(status_code=401, detail="Authentication required")


async def require_admin_context(request: Request) -> AuthContext:
    """Require an administrator console session."""
    context = await require_auth_context(request)
    if not context.is_admin:
        log_event(
            logger,
            "auth.denied",
            reason="admin_required",
            auth_kind=context.kind,
            scope=context.scope,
        )
        raise HTTPException(status_code=403, detail="Administrator access required")
    return context


async def require_read_context(request: Request) -> AuthContext:
    """Require read access through either admin session or API key."""
    return await require_auth_context(request)


async def require_write_context(request: Request) -> AuthContext:
    """Require write access through admin session or a write-scoped API key."""
    context = await require_auth_context(request)
    if not context.can_write:
        log_event(
            logger,
            "auth.denied",
            reason="write_scope_required",
            auth_kind=context.kind,
            scope=context.scope,
        )
        raise HTTPException(status_code=403, detail="API key scope is not allowed")
    return context


def ensure_instance_access(context: AuthContext, instance_id: str, *, write: bool = False) -> None:
    """Validate API key access to a specific instance; admins are unrestricted."""
    if context.is_admin:
        return
    if write and not context.can_write:
        log_event(
            logger,
            "auth.instance_access.denied",
            reason="write_scope_required",
            auth_kind=context.kind,
            scope=context.scope,
            instance_id=instance_id,
        )
        raise HTTPException(status_code=403, detail="API key scope is not allowed")
    if instance_id not in context.instance_ids:
        log_event(
            logger,
            "auth.instance_access.denied",
            reason="instance_not_allowed",
            auth_kind=context.kind,
            scope=context.scope,
            instance_id=instance_id,
        )
        raise HTTPException(status_code=403, detail="API key instance access is not allowed")


def restrict_instance_ids(context: AuthContext, requested: list[str] | None) -> list[str] | None:
    """Return the authorized search instance list for the current context."""
    if context.is_admin:
        return requested

    allowed = sorted(context.instance_ids)
    if requested is None:
        return allowed

    requested_set = set(requested)
    if not requested_set.issubset(context.instance_ids):
        log_event(
            logger,
            "auth.instance_access.denied",
            reason="requested_instances_not_allowed",
            auth_kind=context.kind,
            scope=context.scope,
            requested_count=len(requested_set),
            allowed_count=len(context.instance_ids),
        )
        raise HTTPException(status_code=403, detail="API key instance access is not allowed")
    return list(dict.fromkeys(requested))


def _extract_bearer_token(request: Request) -> str | None:
    auth_header = request.headers.get("authorization") or ""
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    api_key = request.headers.get("x-api-key")
    return api_key.strip() if api_key else None


def reset_llm_client() -> None:
    """Clear the cached LLMClient so it is rebuilt on next access (hot-reload)."""
    get_llm_client.cache_clear()
