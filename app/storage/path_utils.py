"""Path normalization and safety helpers shared by storage-facing code."""

from pathlib import Path
import re
from urllib.parse import unquote


_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


class UnsafePathError(ValueError):
    """Raised when user-controlled input would escape a vault boundary."""


def normalize_vault_path(path: str | None) -> str:
    """Normalize path separators without validating trust or location."""
    return str(path or "").strip().replace("\\", "/")


def validate_vault_relative_path(path: str | None, *, allow_empty: bool = False) -> str:
    """Return a safe vault-relative path or raise UnsafePathError."""
    raw = normalize_vault_path(_decode_path(str(path or "")))
    if not raw:
        if allow_empty:
            return ""
        raise UnsafePathError("Invalid vault path")
    if _CONTROL_CHAR_RE.search(raw):
        raise UnsafePathError("Invalid vault path")
    if raw.startswith("/") or raw.startswith("//") or _WINDOWS_DRIVE_RE.match(raw):
        raise UnsafePathError("Invalid vault path")

    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise UnsafePathError("Invalid vault path")
    if any(":" in part for part in parts):
        raise UnsafePathError("Invalid vault path")
    return "/".join(parts)


def validate_upload_filename(filename: str | None, *, suffix: str = ".md") -> str:
    """Return a safe upload basename or raise UnsafePathError."""
    raw = _decode_path(str(filename or "").strip())
    normalized = raw.replace("\\", "/")
    if not normalized:
        raise UnsafePathError("Invalid upload filename")
    if _CONTROL_CHAR_RE.search(normalized):
        raise UnsafePathError("Invalid upload filename")
    if "/" in normalized or normalized in {".", ".."}:
        raise UnsafePathError("Invalid upload filename")
    if _WINDOWS_DRIVE_RE.match(normalized) or ":" in normalized:
        raise UnsafePathError("Invalid upload filename")
    if normalized.startswith("."):
        raise UnsafePathError("Invalid upload filename")
    if suffix and not normalized.lower().endswith(suffix.lower()):
        raise UnsafePathError("Only .md files are supported")
    return normalized


def resolve_vault_relative_path(vault_path: str | Path, relative_path: str | None) -> Path:
    """Resolve a safe vault-relative path and keep it inside the vault."""
    safe_path = validate_vault_relative_path(relative_path)
    base = Path(vault_path).resolve()
    candidate = (base / safe_path).resolve()
    if candidate == base or not candidate.is_relative_to(base):
        raise UnsafePathError("Invalid vault path")
    return candidate


def _decode_path(value: str) -> str:
    decoded = value
    # Two passes cover common browser/proxy double-encoding without accepting
    # arbitrarily nested encodings as normal input.
    for _ in range(2):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded
