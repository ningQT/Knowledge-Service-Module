"""URL validation helpers for outbound service configuration."""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit


_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "host.docker.internal",
    "metadata.google.internal",
}
_BLOCKED_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("100.100.100.200"),
}


def production_requires_https() -> bool:
    """Return whether production-like env should reject HTTP LLM endpoints."""
    return os.getenv("KSM_ENV", "").strip().lower() in {"prod", "production"}


def llm_ssrf_protection_enabled(explicit: bool | None = None) -> bool:
    """Return whether LLM base URL validation should block local/private targets."""
    if explicit is not None:
        return bool(explicit)
    raw = os.getenv("KSM_LLM_SSRF_PROTECTION")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return production_requires_https()


def validate_llm_base_url(
    raw_url: str | None,
    *,
    require_https: bool = False,
    ssrf_protection: bool | None = None,
) -> str:
    """Validate an outbound LLM base URL and return its stripped value."""
    value = str(raw_url or "").strip().rstrip("/")
    if not value:
        return ""

    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Invalid LLM base URL")
    if (require_https or production_requires_https()) and parsed.scheme != "https":
        raise ValueError("Invalid LLM base URL")

    host = parsed.hostname.strip().lower().strip("[]")
    if llm_ssrf_protection_enabled(ssrf_protection):
        if host in _BLOCKED_HOSTS or host.endswith(".localhost"):
            raise ValueError("Invalid LLM base URL")

        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            _validate_resolved_host(host, parsed.port or (443 if parsed.scheme == "https" else 80))
            return value

        _validate_ip_address(ip)
    return value


def _validate_resolved_host(host: str, port: int) -> None:
    try:
        addrinfo = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Invalid LLM base URL") from exc
    if not addrinfo:
        raise ValueError("Invalid LLM base URL")
    for item in addrinfo:
        sockaddr = item[4]
        if not sockaddr:
            raise ValueError("Invalid LLM base URL")
        try:
            ip = ipaddress.ip_address(str(sockaddr[0]).strip("[]"))
        except ValueError as exc:
            raise ValueError("Invalid LLM base URL") from exc
        _validate_ip_address(ip)


def _validate_ip_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        ip in _BLOCKED_METADATA_IPS
        or ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise ValueError("Invalid LLM base URL")
