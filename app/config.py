"""KSM configuration via environment variables."""

import json
import logging
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

if TYPE_CHECKING:
    from app.storage.database import DatabaseBackend

logger = logging.getLogger(__name__)


def _resolve_env_file() -> str:
    """Resolve .env file path based on KSM_ENV environment variable.

    KSM_ENV=test  → .env.test
    KSM_ENV=prod  → .env.prod
    otherwise     → .env
    """
    env = os.getenv("KSM_ENV", "").strip().lower()
    if env and env != "default":
        return f".env.{env}"
    return ".env"


class Settings(BaseSettings):
    """KSM application settings loaded from environment variables."""

    # Data paths
    data_dir: str = Field(default="./data/vaults", alias="KSM_DATA_DIR")
    template_dir: str = Field(default="./templates", alias="KSM_TEMPLATE_DIR")
    config_dir: str = Field(default="", alias="KSM_CONFIG_DIR")

    # LLM configuration. Runtime defaults are blanked by get_effective_settings()
    # so model credentials are managed from the console, not .env.
    llm_provider: str = Field(default="openai", alias="KSM_LLM_PROVIDER")
    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="KSM_LLM_BASE_URL")
    llm_api_key: str = Field(default="", alias="KSM_LLM_API_KEY")
    llm_model: str = Field(default="gpt-4o", alias="KSM_LLM_MODEL")
    llm_temperature: float = Field(default=0.3, alias="KSM_LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=4096, alias="KSM_LLM_MAX_TOKENS")

    # Phase two reading and generation budgets.
    reading_budget_chars: int = Field(default=39000, alias="KSM_READING_BUDGET_CHARS")
    llm_context_window_chars: int = Field(default=130000, alias="KSM_LLM_CONTEXT_WINDOW_CHARS")
    query_reading_budget: int = Field(default=20000, alias="KSM_QUERY_READING_BUDGET")

    # Document size thresholds.
    tier_tiny_max: int = Field(default=2000, alias="KSM_TIER_TINY_MAX")
    tier_short_max: int = Field(default=5000, alias="KSM_TIER_SHORT_MAX")
    tier_medium_max: int = Field(default=15000, alias="KSM_TIER_MEDIUM_MAX")
    tier_long_max: int = Field(default=50000, alias="KSM_TIER_LONG_MAX")

    # Source note frontmatter guard rails.
    source_note_fm_max_chars: int = Field(
        default=5000,
        validation_alias=AliasChoices("KSM_SOURCE_NOTE_FM_MAX_CHARS", "KSM_FRONTMATTER_MAX_CHARS"),
    )

    # PIT-02: Configurable paper detection and heading levels
    paper_filename_patterns: list[str] = Field(
        default_factory=lambda: [".paper.md", ".论文.md"],
        alias="KSM_PAPER_FILENAME_PATTERNS",
    )
    paper_max_level: int = Field(default=6, alias="KSM_PAPER_MAX_LEVEL")
    default_max_level: int = Field(default=4, alias="KSM_DEFAULT_MAX_LEVEL")

    # HTTP API
    host: str = Field(default="127.0.0.1", alias="KSM_HOST")
    port: int = Field(default=8900, alias="KSM_PORT")
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="KSM_CORS_ORIGINS",
    )
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, alias="KSM_MAX_UPLOAD_BYTES")
    enable_docs: bool = Field(default=True, alias="KSM_ENABLE_DOCS")
    require_https_llm_base_url: bool = Field(default=False, alias="KSM_REQUIRE_HTTPS_LLM_BASE_URL")
    llm_ssrf_protection: bool | None = Field(default=None, alias="KSM_LLM_SSRF_PROTECTION")
    enable_csrf_protection: bool = Field(default=True, alias="KSM_ENABLE_CSRF_PROTECTION")
    csrf_trusted_origins: str = Field(default="", alias="KSM_CSRF_TRUSTED_ORIGINS")
    secure_cookies: bool = Field(default=False, alias="KSM_SECURE_COOKIES")
    trust_proxy_headers: bool = Field(default=False, alias="KSM_TRUST_PROXY_HEADERS")
    rate_limit_enabled: bool = Field(default=True, alias="KSM_RATE_LIMIT_ENABLED")
    rate_limit_window_seconds: int = Field(default=60, alias="KSM_RATE_LIMIT_WINDOW_SECONDS")
    rate_limit_auth_per_window: int = Field(default=10, alias="KSM_RATE_LIMIT_AUTH_PER_WINDOW")
    rate_limit_default_per_window: int = Field(default=120, alias="KSM_RATE_LIMIT_DEFAULT_PER_WINDOW")
    rate_limit_write_per_window: int = Field(default=30, alias="KSM_RATE_LIMIT_WRITE_PER_WINDOW")
    rate_limit_heavy_per_window: int = Field(default=10, alias="KSM_RATE_LIMIT_HEAVY_PER_WINDOW")
    db_backup_dir: str = Field(default="./data/backups", alias="KSM_DB_BACKUP_DIR")
    backup_before_migration: bool = Field(default=True, alias="KSM_BACKUP_BEFORE_MIGRATION")
    sse_token_ttl_seconds: int = Field(default=60, alias="KSM_SSE_TOKEN_TTL_SECONDS")
    expose_error_details: bool = Field(default=False, alias="KSM_EXPOSE_ERROR_DETAILS")

    # Logging
    log_level: str = Field(default="INFO", alias="KSM_LOG_LEVEL")

    # Git sync (optional)
    git_repo_dir: str | None = Field(default=None, alias="KSM_GIT_REPO_DIR")
    git_webhook_secret: str | None = Field(default=None, alias="KSM_GIT_WEBHOOK_SECRET")

    model_config = {"env_file": _resolve_env_file(), "extra": "ignore"}

    def model_post_init(self, __context: object) -> None:
        """Ensure path fields are absolute after loading from .env."""
        if self.data_dir:
            self.data_dir = str(Path(self.data_dir).resolve())
        if self.template_dir:
            self.template_dir = str(Path(self.template_dir).resolve())
        if self.config_dir:
            self.config_dir = str(Path(self.config_dir).resolve())
        if self.db_backup_dir:
            self.db_backup_dir = str(Path(self.db_backup_dir).resolve())


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()


def get_config_dir() -> Path:
    """Get the config directory path.

    Uses KSM_CONFIG_DIR env var if set, otherwise falls back to the
    package's built-in configs/ directory.
    """
    settings = get_settings()
    if settings.config_dir:
        return Path(settings.config_dir)
    return Path(__file__).parent.parent / "configs"


# --- Phase 3: Effective settings (DB override merge) ---

_LLM_CONSOLE_DEFAULTS = {
    "llm_provider": "",
    "llm_base_url": "",
    "llm_api_key": "",
    "llm_model": "",
    "llm_temperature": 0.3,
    "llm_max_tokens": 4096,
}

_effective_settings: Settings | None = None
_settings_lock = threading.Lock()


def _build_effective_settings(db: "DatabaseBackend | None" = None) -> Settings:
    """Merge environment base + database LLM config into a final Settings instance.

    Non-LLM settings still come from the environment. LLM provider credentials are
    blank by default and only become effective when saved from the console.
    """
    base = Settings().model_copy(update=_LLM_CONSOLE_DEFAULTS)
    if db is None:
        return base

    try:
        rows = db.get_settings("llm.")
    except Exception:
        logger.warning("Failed to read settings from database, using .env defaults")
        return base

    if not rows:
        return base

    override_dict: dict = {}
    for row in rows:
        # "llm.base_url" → "llm_base_url" to match Settings field names
        field = "llm_" + row["key"][4:]
        if field not in Settings.model_fields:
            logger.warning("Unknown settings field %s (from key %s), skipping", field, row["key"])
            continue
        try:
            override_dict[field] = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            logger.warning("Invalid JSON for settings key %s, skipping", row["key"])

    if not override_dict:
        return base

    return base.model_copy(update=override_dict)


def get_effective_settings(db: "DatabaseBackend | None" = None) -> Settings:
    """Return the merged effective settings (.env base + DB overrides).

    First call lazily initialises from the database; subsequent calls
    return the cached instance until ``reload_effective_settings`` is called.
    """
    global _effective_settings
    with _settings_lock:
        if _effective_settings is None:
            if db is None:
                try:
                    from app.api.dependencies import get_db
                    db = get_db()
                except Exception:
                    db = None
            _effective_settings = _build_effective_settings(db)
        return _effective_settings


def reload_effective_settings(db: "DatabaseBackend | None" = None) -> Settings:
    """Force-rebuild the effective settings cache (called after hot-update)."""
    global _effective_settings
    with _settings_lock:
        _effective_settings = _build_effective_settings(db)
        return _effective_settings
