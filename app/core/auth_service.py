"""Authentication and API key management services."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.storage.database import DatabaseBackend


PASSWORD_ITERATIONS = 260_000
SESSION_TTL_DAYS = 7
API_KEY_PREFIX_LENGTH = 12
VALID_SCOPES = {"read", "write"}


@dataclass(frozen=True)
class AuthContext:
    """Authenticated request context for console sessions and API clients."""

    kind: str
    user_id: str | None = None
    username: str | None = None
    client_id: str | None = None
    client_name: str | None = None
    scope: str = "read"
    instance_ids: set[str] = field(default_factory=set)

    @property
    def is_admin(self) -> bool:
        return self.kind == "admin"

    @property
    def can_write(self) -> bool:
        return self.is_admin or self.scope == "write"


class AuthService:
    """Manage administrator sessions and external API keys."""

    def __init__(self, db: DatabaseBackend):
        self.db = db

    def has_admin(self) -> bool:
        rows = self.db.execute("SELECT 1 FROM admin_users LIMIT 1")
        return bool(rows)

    def setup_admin(self, username: str, password: str) -> dict[str, Any]:
        if self.has_admin():
            raise ValueError("Admin setup already completed")

        clean_username = username.strip()
        if not clean_username:
            raise ValueError("Username is required")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")

        now = _now()
        salt = secrets.token_hex(16)
        iterations = PASSWORD_ITERATIONS
        self.db.execute(
            """INSERT INTO admin_users
               (id, username, password_hash, password_salt, password_iterations, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                f"admin_{uuid.uuid4().hex[:12]}",
                clean_username,
                _hash_password(password, salt, iterations),
                salt,
                iterations,
                now,
                now,
            ),
        )
        return self.get_admin_by_username(clean_username)

    def get_admin_by_username(self, username: str) -> dict[str, Any]:
        rows = self.db.execute(
            """SELECT id, username, created_at, updated_at
               FROM admin_users
               WHERE username = ?
               LIMIT 1""",
            (username,),
        )
        if not rows:
            raise ValueError("Invalid credentials")
        return rows[0]

    def verify_admin(self, username: str, password: str) -> dict[str, Any] | None:
        rows = self.db.execute(
            """SELECT id, username, password_hash, password_salt, password_iterations, created_at, updated_at
               FROM admin_users
               WHERE username = ?
               LIMIT 1""",
            (username.strip(),),
        )
        if not rows:
            return None

        row = rows[0]
        expected = _hash_password(password, row["password_salt"], int(row["password_iterations"]))
        if not hmac.compare_digest(expected, row["password_hash"]):
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def create_session(self, user_id: str) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        token_hash = _hash_token(token)
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        expires_at = (now_dt + timedelta(days=SESSION_TTL_DAYS)).isoformat()
        self.db.execute(
            """INSERT INTO admin_sessions
               (token_hash, user_id, created_at, last_seen_at, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            (token_hash, user_id, now, now, expires_at),
        )
        return token, expires_at

    def get_session_context(self, token: str) -> AuthContext | None:
        token_hash = _hash_token(token)
        now = _now()
        rows = self.db.execute(
            """SELECT s.token_hash, s.user_id, s.expires_at, u.username
               FROM admin_sessions s
               JOIN admin_users u ON u.id = s.user_id
               WHERE s.token_hash = ?
               LIMIT 1""",
            (token_hash,),
        )
        if not rows:
            return None

        row = rows[0]
        if row["expires_at"] <= now:
            self.db.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (token_hash,))
            return None

        self.db.execute(
            "UPDATE admin_sessions SET last_seen_at = ? WHERE token_hash = ?",
            (now, token_hash),
        )
        return AuthContext(kind="admin", user_id=row["user_id"], username=row["username"], scope="write")

    def delete_session(self, token: str) -> None:
        self.db.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (_hash_token(token),))

    def create_api_key(self, name: str, scope: str, instance_ids: list[str]) -> tuple[dict[str, Any], str]:
        clean_name = name.strip()
        clean_scope = scope.strip()
        if not clean_name:
            raise ValueError("API key name is required")
        if clean_scope not in VALID_SCOPES:
            raise ValueError("Invalid API key scope")
        self._validate_instance_ids(instance_ids)

        raw_key = _generate_api_key()
        now = _now()
        client_id = f"ak_{uuid.uuid4().hex[:12]}"
        self.db.execute(
            """INSERT INTO api_clients
               (id, name, key_prefix, key_hash, scope, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
            (client_id, clean_name, raw_key[:API_KEY_PREFIX_LENGTH], _hash_token(raw_key), clean_scope, now, now),
        )
        self._replace_api_key_instances(client_id, instance_ids)
        return self.get_api_key(client_id), raw_key

    def list_api_keys(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """SELECT id, name, key_prefix, scope, enabled, created_at, updated_at, last_used_at
               FROM api_clients
               ORDER BY created_at DESC"""
        )
        return [self._with_instances(row) for row in rows]

    def get_api_key(self, client_id: str) -> dict[str, Any]:
        rows = self.db.execute(
            """SELECT id, name, key_prefix, scope, enabled, created_at, updated_at, last_used_at
               FROM api_clients
               WHERE id = ?
               LIMIT 1""",
            (client_id,),
        )
        if not rows:
            raise ValueError("API key not found")
        return self._with_instances(rows[0])

    def update_api_key(
        self,
        client_id: str,
        *,
        name: str | None = None,
        scope: str | None = None,
        enabled: bool | None = None,
        instance_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        current = self.get_api_key(client_id)
        next_name = current["name"] if name is None else name.strip()
        next_scope = current["scope"] if scope is None else scope.strip()
        next_enabled = current["enabled"] if enabled is None else bool(enabled)

        if not next_name:
            raise ValueError("API key name is required")
        if next_scope not in VALID_SCOPES:
            raise ValueError("Invalid API key scope")
        if instance_ids is not None:
            self._validate_instance_ids(instance_ids)

        self.db.execute(
            """UPDATE api_clients
               SET name = ?, scope = ?, enabled = ?, updated_at = ?
               WHERE id = ?""",
            (next_name, next_scope, int(next_enabled), _now(), client_id),
        )
        if instance_ids is not None:
            self._replace_api_key_instances(client_id, instance_ids)
        return self.get_api_key(client_id)

    def delete_api_key(self, client_id: str) -> None:
        self.get_api_key(client_id)
        self.db.execute("DELETE FROM api_clients WHERE id = ?", (client_id,))

    def rotate_api_key(self, client_id: str) -> tuple[dict[str, Any], str]:
        self.get_api_key(client_id)
        raw_key = _generate_api_key()
        self.db.execute(
            """UPDATE api_clients
               SET key_prefix = ?, key_hash = ?, updated_at = ?
               WHERE id = ?""",
            (raw_key[:API_KEY_PREFIX_LENGTH], _hash_token(raw_key), _now(), client_id),
        )
        return self.get_api_key(client_id), raw_key

    def get_api_key_context(self, raw_key: str) -> AuthContext | None:
        key_hash = _hash_token(raw_key.strip())
        rows = self.db.execute(
            """SELECT id, name, scope
               FROM api_clients
               WHERE key_hash = ? AND enabled = 1
               LIMIT 1""",
            (key_hash,),
        )
        if not rows:
            return None
        row = rows[0]
        instance_rows = self.db.execute(
            "SELECT instance_id FROM api_client_instances WHERE client_id = ?",
            (row["id"],),
        )
        self.db.execute(
            "UPDATE api_clients SET last_used_at = ? WHERE id = ?",
            (_now(), row["id"]),
        )
        return AuthContext(
            kind="api_key",
            client_id=row["id"],
            client_name=row["name"],
            scope=row["scope"],
            instance_ids={item["instance_id"] for item in instance_rows},
        )

    def _with_instances(self, row: dict[str, Any]) -> dict[str, Any]:
        instance_rows = self.db.execute(
            "SELECT instance_id FROM api_client_instances WHERE client_id = ? ORDER BY instance_id",
            (row["id"],),
        )
        result = dict(row)
        result["enabled"] = bool(result.get("enabled"))
        result["instance_ids"] = [item["instance_id"] for item in instance_rows]
        return result

    def _replace_api_key_instances(self, client_id: str, instance_ids: list[str]) -> None:
        self.db.execute("DELETE FROM api_client_instances WHERE client_id = ?", (client_id,))
        unique_ids = list(dict.fromkeys(instance_ids))
        if unique_ids:
            self.db.executemany(
                "INSERT INTO api_client_instances (client_id, instance_id) VALUES (?, ?)",
                [(client_id, instance_id) for instance_id in unique_ids],
            )

    def _validate_instance_ids(self, instance_ids: list[str]) -> None:
        unique_ids = list(dict.fromkeys(instance_ids))
        if not unique_ids:
            return
        placeholders = ",".join("?" * len(unique_ids))
        rows = self.db.execute(
            f"SELECT id FROM instances WHERE id IN ({placeholders})",
            tuple(unique_ids),
        )
        found = {row["id"] for row in rows}
        missing = [instance_id for instance_id in unique_ids if instance_id not in found]
        if missing:
            raise ValueError(f"Unknown instance id: {missing[0]}")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash_password(password: str, salt_hex: str, iterations: int) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        iterations,
    )
    return digest.hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generate_api_key() -> str:
    return f"ksm_{secrets.token_urlsafe(32)}"
