"""FastAPI application factory."""

from contextlib import asynccontextmanager
from pathlib import Path
import logging
import re
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError

from app.config import get_settings
from app.exceptions import KSMError
from app.observability import configure_logging, log_event, new_log_id, reset_log_id, set_log_id
from app.security.request_guards import InMemoryRateLimiter, csrf_origin_allowed, request_scheme

logger = logging.getLogger(__name__)
LOG_ID_HEADER = "X-Log-Id"
_LOG_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)


def _http_error_code(status_code: int, detail: object) -> str:
    """Map existing HTTPException detail text to a stable frontend translation code."""
    text = str(detail)
    if text == "Only .md files are supported":
        return "INGEST_ONLY_MD"
    if text == "Invalid upload filename":
        return "INGEST_FILENAME_INVALID"
    if text == "Uploaded file is too large":
        return "INGEST_FILE_TOO_LARGE"
    if text == "File must be UTF-8 encoded":
        return "INGEST_FILE_UTF8"
    if "already has a running ingest job" in text:
        return "INGEST_JOB_ALREADY_RUNNING"
    if "is not running" in text:
        return "JOB_NOT_RUNNING"
    if "Job '" in text and "not found" in text:
        return "JOB_NOT_FOUND"
    if text == "Request body must contain at least one field":
        return "SETTINGS_EMPTY_UPDATE"
    if text == "Invalid LLM base URL":
        return "SETTINGS_LLM_BASE_URL_INVALID"
    if text == "CSRF origin forbidden":
        return "CSRF_ORIGIN_FORBIDDEN"
    if text == "Rate limit exceeded":
        return "RATE_LIMITED"
    if "Instance '" in text and "not found" in text:
        return "INSTANCE_NOT_FOUND"
    if text.startswith("Instance name already exists"):
        return "INSTANCE_ALREADY_EXISTS"
    if text == "Instance name is required":
        return "INSTANCE_NAME_REQUIRED"
    if text == "Instance vault path is outside the configured data directory":
        return "INSTANCE_VAULT_PATH_UNSAFE"
    if "Note " in text and "not found" in text:
        return "NOTE_NOT_FOUND"
    if text == "Invalid note verification status":
        return "NOTE_VERIFICATION_INVALID"
    if text == "Invalid vault path":
        return "VAULT_PATH_INVALID"
    if text == "Authentication required":
        return "AUTH_REQUIRED"
    if text == "Invalid credentials":
        return "AUTH_INVALID_CREDENTIALS"
    if text == "Admin setup required":
        return "AUTH_SETUP_REQUIRED"
    if text == "Admin setup already completed":
        return "AUTH_SETUP_ALREADY_DONE"
    if text == "Administrator access required":
        return "AUTH_FORBIDDEN"
    if text == "API key scope is not allowed":
        return "API_KEY_SCOPE_FORBIDDEN"
    if text == "API key instance access is not allowed":
        return "AUTH_FORBIDDEN"
    if text == "Invalid API key":
        return "API_KEY_INVALID"
    return f"HTTP_{status_code}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan."""
    from app.api.dependencies import get_db
    db = get_db()
    db.migrate_fts_to_contentless()
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_level)
    frontend_dist = (Path(__file__).resolve().parent.parent.parent / "frontend" / "dist").resolve()
    app = FastAPI(
        title="KSM - Knowledge Service Module",
        description="Independent knowledge infrastructure module.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url="/redoc" if settings.enable_docs else None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[LOG_ID_HEADER],
    )
    rate_limiter = InMemoryRateLimiter(settings)

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        log_id = _request_log_id(request)
        token = set_log_id(log_id)
        started = time.perf_counter()
        path = request.url.path
        method = request.method
        log_event(
            logger,
            "request.start",
            method=method,
            path=path,
            client_host=request.client.host if request.client else None,
        )
        if path.startswith("/api/"):
            log_event(logger, "api.request", method=method, path=path)
        if not rate_limiter.allow(request):
            response = JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "code": "RATE_LIMITED",
                    "detail": "Rate limit exceeded",
                },
            )
            response.headers[LOG_ID_HEADER] = log_id
            _set_security_headers(response, request)
            reset_log_id(token)
            return response
        if not csrf_origin_allowed(request, settings):
            response = JSONResponse(
                status_code=403,
                content={
                    "error": "CSRF origin forbidden",
                    "code": "CSRF_ORIGIN_FORBIDDEN",
                    "detail": "CSRF origin forbidden",
                },
            )
            response.headers[LOG_ID_HEADER] = log_id
            _set_security_headers(response, request)
            reset_log_id(token)
            return response
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = _duration_ms(started)
            log_event(
                logger,
                "request.error",
                level=logging.ERROR,
                method=method,
                path=path,
                duration_ms=duration_ms,
                exc_info=True,
            )
            reset_log_id(token)
            raise

        spa_response = _spa_fallback_response(request, response.status_code, frontend_dist)
        if spa_response is not None:
            response = spa_response
        response.headers[LOG_ID_HEADER] = log_id
        _set_security_headers(response, request)
        log_event(
            logger,
            "request.done",
            method=method,
            path=path,
            status_code=response.status_code,
            duration_ms=_duration_ms(started),
        )
        if path.startswith("/api/"):
            log_event(
                logger,
                "api.response",
                method=method,
                path=path,
                status_code=response.status_code,
                duration_ms=_duration_ms(started),
            )
        reset_log_id(token)
        return response

    @app.exception_handler(KSMError)
    async def ksm_error_handler(request: Request, exc: KSMError):
        status_map = {
            "INSTANCE_NOT_FOUND": 404,
            "INSTANCE_ALREADY_EXISTS": 409,
            "TEMPLATE_NOT_FOUND": 404,
            "INVALID_SCHEMA": 422,
            "INGEST_FAILED": 422,
            "SEARCH_PARAM_ERROR": 400,
            "NODE_READ_ERROR": 500,
            "COMPREHENSION_ERROR": 500,
            "SYNC_FAILED": 500,
            "REINDEX_FAILED": 500,
        }
        status = status_map.get(exc.code, 500)
        log_event(
            logger,
            "api.error",
            level=logging.ERROR if status >= 500 else logging.WARNING,
            method=request.method,
            path=request.url.path,
            status_code=status,
            code=exc.code,
            error_type=exc.__class__.__name__,
        )
        return JSONResponse(
            status_code=status,
            content=_error_response_content(status, str(exc), exc.code, str(exc), settings),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = str(exc.detail)
        code = _http_error_code(exc.status_code, exc.detail)
        log_event(
            logger,
            "api.error",
            level=logging.ERROR if exc.status_code >= 500 else logging.WARNING,
            method=request.method,
            path=request.url.path,
            status_code=exc.status_code,
            code=code,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_response_content(exc.status_code, detail, code, detail, settings),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        log_event(
            logger,
            "api.error",
            level=logging.WARNING,
            method=request.method,
            path=request.url.path,
            status_code=422,
            code="REQUEST_VALIDATION_FAILED",
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": "Request validation failed",
                "code": "REQUEST_VALIDATION_FAILED",
                "detail": exc.errors(),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        log_event(
            logger,
            "api.error",
            level=logging.ERROR,
            method=request.method,
            path=request.url.path,
            status_code=500,
            code="HTTP_500",
            error_type=exc.__class__.__name__,
            exc_info=True,
        )
        detail = str(exc) or "Internal server error"
        return JSONResponse(
            status_code=500,
            content=_error_response_content(500, detail, "HTTP_500", detail, settings),
        )

    from app.api.routes.api_keys import router as api_keys_router
    from app.api.routes.auth import router as auth_router
    from app.api.routes.graph import router as graph_router
    from app.api.routes.ingest import router as ingest_router
    from app.api.routes.instances import router as instances_router
    from app.api.routes.notes import router as notes_router
    from app.api.routes.ontology import router as ontology_router
    from app.api.routes.search import router as search_router
    from app.api.routes.search_lexicon import router as search_lexicon_router
    from app.api.routes.settings import router as settings_router
    from app.api.routes.sync import router as sync_router

    app.include_router(auth_router)
    app.include_router(api_keys_router)
    app.include_router(instances_router)
    app.include_router(ingest_router)
    app.include_router(search_router)
    app.include_router(search_lexicon_router)
    app.include_router(ontology_router)
    app.include_router(sync_router)
    app.include_router(notes_router)
    app.include_router(graph_router)
    app.include_router(settings_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


def _request_log_id(request: Request) -> str:
    incoming = (request.headers.get(LOG_ID_HEADER) or "").strip()
    if incoming and _LOG_ID_RE.fullmatch(incoming):
        return incoming
    return new_log_id()


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _cors_origins(value: str) -> list[str]:
    origins = [item.strip() for item in str(value or "").split(",") if item.strip()]
    return origins or ["http://localhost:5173", "http://127.0.0.1:5173"]


def _set_security_headers(response, request: Request) -> None:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    if request_scheme(request, get_settings()) == "https":
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )


def _spa_fallback_response(request: Request, status_code: int, frontend_dist: Path):
    if status_code != 404 or request.method not in {"GET", "HEAD"}:
        return None
    full_path = request.url.path.lstrip("/")
    if full_path.startswith("api/") or full_path in {"docs", "redoc", "openapi.json"}:
        return None
    file_path = (frontend_dist / full_path).resolve()
    if file_path.is_relative_to(frontend_dist) and file_path.is_file():
        return FileResponse(file_path)
    index = frontend_dist / "index.html"
    if index.is_file():
        return FileResponse(index)
    return None


def _error_response_content(
    status_code: int,
    error: str,
    code: str,
    detail: object,
    settings,
) -> dict:
    if status_code >= 500 and not settings.expose_error_details:
        return {
            "error": "Internal server error",
            "code": code,
            "detail": "Internal server error",
        }
    return {"error": error, "code": code, "detail": detail}
