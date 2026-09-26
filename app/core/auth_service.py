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
VALID_INSTANCE_PERMISSIONS = {"read", "edit"}


@dataclass(frozen=True)
class AuthContext:
    """Authenticated request context for console sessions and API clients."""

    kind: str
    user_id: str | None = None
    username: str | None = None
    role: str = "user"
    enabled: bool = True
    client_id: str | None = None
    client_name: str | None = None
    scope: str = "read"
    instance_ids: set[str] = field(default_factory=set)
    instance_permissions: dict[str, str] = field(default_factory=dict)

    @property
    def is_admin(self) -> bool:
        """Return whether this is an administrator console session."""
        return self.kind == "admin" and self.role == "admin"

    @property
    def is_console(self) -> bool:
        """Return whether this context comes from a browser console session."""
        return self.kind in {"admin", "user"}

    @property
    def can_write(self) -> bool:
        """Return whether the context has any effective write capability."""
        if self.is_admin:
            return True
        return any(permission == "edit" for permission in self.instance_permissions.values())

    def permission_for(self, instance_id: str) -> str | None:
        """Return the effective permission for one instance.

        Args:
            instance_id: Knowledge-base instance identifier.

        Returns:
            ``read``、``edit`` 或 ``None``。
        """
        if self.is_admin:
            return "edit"
        return self.instance_permissions.get(instance_id)


class AuthService:
    """Manage administrator sessions and external API keys."""

    def __init__(self, db: DatabaseBackend):
        self.db = db

    def has_admin(self) -> bool:
        """Return whether an administrator account exists."""
        rows = self.db.execute("SELECT 1 FROM admin_users WHERE role = 'admin' LIMIT 1")
        return bool(rows)

    def _admin_id(self) -> str | None:
        rows = self.db.execute(
            "SELECT id FROM admin_users WHERE role = 'admin' ORDER BY created_at LIMIT 1"
        )
        return rows[0]["id"] if rows else None

    def setup_admin(self, username: str, password: str) -> dict[str, Any]:
        """Create the initial administrator account."""
        if self.has_admin():
            raise ValueError("Admin setup already completed")
        clean_username = self._validate_username(username)
        self._validate_password(password)
        now = _now()
        salt = secrets.token_hex(16)
        iterations = PASSWORD_ITERATIONS
        account_id = f"admin_{uuid.uuid4().hex[:12]}"
        self.db.execute(
            """INSERT INTO admin_users
               (id, username, password_hash, password_salt, password_iterations,
                role, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'admin', 1, ?, ?)""",
            (
                account_id,
                clean_username,
                _hash_password(password, salt, iterations),
                salt,
                iterations,
                now,
                now,
            ),
        )
        return self.get_account(account_id)

    def get_account(self, account_id: str) -> dict[str, Any]:
        """Return one account by identifier."""
        rows = self.db.execute(
            """SELECT id, username, role, enabled, created_at, updated_at
               FROM admin_users WHERE id = ? LIMIT 1""",
            (account_id,),
        )
        if not rows:
            raise ValueError("Account not found")
        return _account_dict(rows[0])

    def get_account_by_username(self, username: str) -> dict[str, Any]:
        """Return one account by username."""
        rows = self.db.execute(
            """SELECT id, username, role, enabled, created_at, updated_at
               FROM admin_users WHERE username = ? LIMIT 1""",
            (username.strip(),),
        )
        if not rows:
            raise ValueError("Invalid credentials")
        return _account_dict(rows[0])

    def get_admin_by_username(self, username: str) -> dict[str, Any]:
        """Return an administrator by username for compatibility."""
        account = self.get_account_by_username(username)
        if account["role"] != "admin":
            raise ValueError("Invalid credentials")
        return account

    def verify_credentials(self, username: str, password: str) -> dict[str, Any] | None:
        """Verify username and password and return the enabled account."""
        rows = self.db.execute(
            """SELECT id, username, password_hash, password_salt, password_iterations,
                      role, enabled, created_at, updated_at
               FROM admin_users WHERE username = ? LIMIT 1""",
            (username.strip(),),
        )
        if not rows:
            return None
        row = rows[0]
        if not bool(row["enabled"]):
            return None
        expected = _hash_password(
            password,
            row["password_salt"],
            int(row["password_iterations"]),
        )
        if not hmac.compare_digest(expected, row["password_hash"]):
            return None
        return _account_dict(row)

    def verify_admin(self, username: str, password: str) -> dict[str, Any] | None:
        """Verify an administrator login for compatibility."""
        account = self.verify_credentials(username, password)
        return account if account and account["role"] == "admin" else None

    def list_accounts(self) -> list[dict[str, Any]]:
        """List ordinary accounts for administrator management."""
        rows = self.db.execute(
            """SELECT id, username, role, enabled, created_at, updated_at
               FROM admin_users
               WHERE role = 'user'
               ORDER BY created_at DESC"""
        )
        return [_account_dict(row) for row in rows]

    def create_user_account(
        self,
        username: str,
        password: str,
        *,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Create one ordinary account."""
        clean_username = self._validate_username(username)
        self._validate_password(password)
        if self.db.execute(
            "SELECT 1 FROM admin_users WHERE username = ? LIMIT 1",
            (clean_username,),
        ):
            raise ValueError("Username already exists")
        now = _now()
        salt = secrets.token_hex(16)
        iterations = PASSWORD_ITERATIONS
        account_id = f"user_{uuid.uuid4().hex[:12]}"
        self.db.execute(
            """INSERT INTO admin_users
               (id, username, password_hash, password_salt, password_iterations,
                role, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'user', ?, ?, ?)""",
            (
                account_id,
                clean_username,
                _hash_password(password, salt, iterations),
                salt,
                iterations,
                int(enabled),
                now,
                now,
            ),
        )
        return self.get_account(account_id)

    def set_account_enabled(self, account_id: str, enabled: bool) -> dict[str, Any]:
        """Enable or disable an ordinary account and its API keys."""
        account = self.get_account(account_id)
        if account["role"] == "admin":
            raise ValueError("Administrator account cannot be disabled")
        with self.db.transaction():
            self.db.execute(
                "UPDATE admin_users SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), _now(), account_id),
            )
            if not enabled:
                self.db.execute(
                    "DELETE FROM admin_sessions WHERE user_id = ?",
                    (account_id,),
                )
                self.db.execute(
                    "UPDATE api_clients SET enabled = 0, updated_at = ? WHERE owner_account_id = ?",
                    (_now(), account_id),
                )
                from app.core.job_access import job_access_registry

                job_access_registry.cancel_for_account(account_id, "account_disabled")
        return self.get_account(account_id)

    def reset_password(self, account_id: str, new_password: str) -> None:
        """Reset an ordinary account password."""
        account = self.get_account(account_id)
        if account["role"] == "admin":
            raise ValueError("Administrator password must be changed through personal center")
        self._validate_password(new_password)
        self._set_password(account_id, new_password)
        self.db.execute("DELETE FROM admin_sessions WHERE user_id = ?", (account_id,))

    def change_password(
        self,
        account_id: str,
        current_password: str,
        new_password: str,
    ) -> None:
        """Change the current account password after checking the old password."""
        account = self.get_account(account_id)
        if not self.verify_credentials(account["username"], current_password):
            raise ValueError("Current password is invalid")
        self._validate_password(new_password)
        self._set_password(account_id, new_password)

    def delete_account(self, account_id: str) -> None:
        """Delete an ordinary account and transfer owned instances to admin."""
        account = self.get_account(account_id)
        if account["role"] == "admin":
            raise ValueError("Administrator account cannot be deleted")
        admin_id = self._admin_id()
        if not admin_id:
            raise ValueError("Administrator account not found")
        with self.db.transaction():
            self.db.execute("DELETE FROM admin_sessions WHERE user_id = ?", (account_id,))
            self.db.execute("DELETE FROM api_clients WHERE owner_account_id = ?", (account_id,))
            self.db.execute(
                "DELETE FROM account_instance_permissions WHERE account_id = ?",
                (account_id,),
            )
            self.db.execute(
                "UPDATE instances SET owner_account_id = ?, updated_at = ? "
                "WHERE owner_account_id = ?",
                (admin_id, _now(), account_id),
            )
            self.db.execute("DELETE FROM admin_users WHERE id = ?", (account_id,))

    def _set_password(self, account_id: str, password: str) -> None:
        salt = secrets.token_hex(16)
        iterations = PASSWORD_ITERATIONS
        self.db.execute(
            """UPDATE admin_users
               SET password_hash = ?, password_salt = ?, password_iterations = ?, updated_at = ?
               WHERE id = ?""",
            (
                _hash_password(password, salt, iterations),
                salt,
                iterations,
                _now(),
                account_id,
            ),
        )

    def _validate_username(self, username: str) -> str:
        clean_username = username.strip()
        if not clean_username:
            raise ValueError("Username is required")
        return clean_username

    def _validate_password(self, password: str) -> None:
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")

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
        """Resolve an enabled console session into an authorization context."""
        token_hash = _hash_token(token)
        now = _now()
        rows = self.db.execute(
            """SELECT s.user_id, s.expires_at, u.username, u.role, u.enabled
               FROM admin_sessions s
               JOIN admin_users u ON u.id = s.user_id
               WHERE s.token_hash = ?
               LIMIT 1""",
            (token_hash,),
        )
        if not rows:
            return None

        row = rows[0]
        if row["expires_at"] <= now or not bool(row["enabled"]):
            self.db.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (token_hash,))
            return None

        self.db.execute(
            "UPDATE admin_sessions SET last_seen_at = ? WHERE token_hash = ?",
            (now, token_hash),
        )
        permissions = (
            {} if row["role"] == "admin" else self._load_instance_permissions(row["user_id"])
        )
        return AuthContext(
            kind="admin" if row["role"] == "admin" else "user",
            user_id=row["user_id"],
            username=row["username"],
            role=row["role"],
            enabled=True,
            scope="write",
            instance_ids=set(permissions),
            instance_permissions=permissions,
        )

    def delete_session(self, token: str) -> None:
        self.db.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (_hash_token(token),))

    def _load_instance_permissions(self, account_id: str) -> dict[str, str]:
        rows = self.db.execute(
            """SELECT i.id AS instance_id,
                      CASE
                        WHEN i.owner_account_id = ? THEN 'edit'
                        ELSE p.permission
                      END AS permission
               FROM instances i
               LEFT JOIN account_instance_permissions p
                 ON p.instance_id = i.id AND p.account_id = ?
               WHERE i.owner_account_id = ? OR p.account_id = ?""",
            (account_id, account_id, account_id, account_id),
        )
        return {
            row["instance_id"]: row["permission"]
            for row in rows
            if row.get("permission") in VALID_INSTANCE_PERMISSIONS
        }

    def _editable_instance_ids(self, account_id: str) -> set[str]:
        return {
            instance_id
            for instance_id, permission in self._load_instance_permissions(account_id).items()
            if permission == "edit"
        }

    def can_manage_instance(self, account_id: str, instance_id: str, *, is_admin: bool) -> bool:
        """Return whether an actor can manage instance permissions."""
        if is_admin:
            return True
        rows = self.db.execute(
            "SELECT owner_account_id FROM instances WHERE id = ? LIMIT 1",
            (instance_id,),
        )
        return bool(rows and rows[0]["owner_account_id"] == account_id)

    def get_instance_permissions(
        self,
        instance_id: str,
        *,
        actor_id: str,
        is_admin: bool,
    ) -> dict[str, Any]:
        """Return owner, ordinary-account grants and affected key counts."""
        if not self.can_manage_instance(actor_id, instance_id, is_admin=is_admin):
            raise ValueError("Instance access denied")
        instance_rows = self.db.execute(
            """SELECT i.id, i.name, i.owner_account_id, u.username AS owner_username
               FROM instances i
               LEFT JOIN admin_users u ON u.id = i.owner_account_id
               WHERE i.id = ? LIMIT 1""",
            (instance_id,),
        )
        if not instance_rows:
            raise ValueError("Instance not found")
        instance = instance_rows[0]
        rows = self.db.execute(
            """SELECT u.id, u.username, u.enabled,
                      COALESCE(p.permission, 'none') AS permission
               FROM admin_users u
               LEFT JOIN account_instance_permissions p
                 ON p.account_id = u.id AND p.instance_id = ?
               WHERE u.role = 'user' AND u.id != ?
               ORDER BY u.username""",
            (instance_id, instance["owner_account_id"]),
        )
        accounts = []
        for row in rows:
            accounts.append(
                {
                    "account_id": row["id"],
                    "username": row["username"],
                    "enabled": bool(row["enabled"]),
                    "permission": row["permission"],
                    "affected_api_key_count": self._affected_key_count(row["id"], instance_id)
                    if row["permission"] == "edit"
                    else 0,
                }
            )
        return {
            "instance_id": instance_id,
            "instance_name": instance["name"],
            "owner": {
                "account_id": instance["owner_account_id"],
                "username": instance["owner_username"],
                "permission": "owner",
            },
            "accounts": accounts,
        }

    def update_instance_permissions(
        self,
        instance_id: str,
        updates: list[dict[str, str]],
        *,
        actor_id: str,
        is_admin: bool,
    ) -> dict[str, Any]:
        """Atomically update ordinary-account permissions for one instance."""
        if not self.can_manage_instance(actor_id, instance_id, is_admin=is_admin):
            raise ValueError("Instance access denied")
        instance_rows = self.db.execute(
            "SELECT owner_account_id FROM instances WHERE id = ? LIMIT 1",
            (instance_id,),
        )
        if not instance_rows:
            raise ValueError("Instance not found")
        owner_account_id = instance_rows[0]["owner_account_id"]
        with self.db.transaction():
            for update in updates:
                account_id = update["account_id"]
                permission = update["permission"]
                if permission not in {"none", "read", "edit"}:
                    raise ValueError("Invalid instance permission")
                if account_id == owner_account_id:
                    raise ValueError("Instance owner permission cannot be changed")
                target = self.db.execute(
                    "SELECT role FROM admin_users WHERE id = ? LIMIT 1",
                    (account_id,),
                )
                if not target or target[0]["role"] != "user":
                    raise ValueError("Account not found")
                previous = self.db.execute(
                    """SELECT permission FROM account_instance_permissions
                       WHERE account_id = ? AND instance_id = ? LIMIT 1""",
                    (account_id, instance_id),
                )
                old_permission = previous[0]["permission"] if previous else "none"
                if old_permission in {"read", "edit"} and permission == "none":
                    from app.core.job_access import job_access_registry

                    job_access_registry.cancel_for_account_instance(
                        account_id,
                        instance_id,
                        "read_permission_revoked",
                        access_mode="read",
                    )
                if old_permission == "edit" and permission != "edit":
                    self._delete_key_bindings(account_id, instance_id)
                    from app.core.job_access import job_access_registry

                    job_access_registry.cancel_for_account_instance(
                        account_id,
                        instance_id,
                        "edit_permission_revoked",
                        access_mode="write",
                    )
                if permission == "none":
                    self.db.execute(
                        "DELETE FROM account_instance_permissions "
                        "WHERE account_id = ? AND instance_id = ?",
                        (account_id, instance_id),
                    )
                else:
                    now = _now()
                    self.db.execute(
                        """INSERT INTO account_instance_permissions
                           (account_id, instance_id, permission,
                            granted_by_account_id, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?)
                           ON CONFLICT(account_id, instance_id) DO UPDATE SET
                             permission = excluded.permission,
                             granted_by_account_id = excluded.granted_by_account_id,
                             updated_at = excluded.updated_at""",
                        (account_id, instance_id, permission, actor_id, now, now),
                    )
        return self.get_instance_permissions(instance_id, actor_id=actor_id, is_admin=is_admin)

    def list_bound_api_keys(
        self, instance_id: str, *, actor_id: str, is_admin: bool
    ) -> list[dict[str, Any]]:
        """Return key summaries bound to an instance without secrets."""
        if not self.can_manage_instance(actor_id, instance_id, is_admin=is_admin):
            raise ValueError("Instance access denied")
        instance_rows = self.db.execute(
            "SELECT 1 FROM instances WHERE id = ? LIMIT 1",
            (instance_id,),
        )
        if not instance_rows:
            raise ValueError("Instance not found")
        rows = self.db.execute(
            """SELECT c.id, c.name, c.key_prefix, c.scope, c.enabled,
                      c.owner_account_id, u.username AS owner_username, c.last_used_at
               FROM api_clients c
               JOIN api_client_instances ci ON ci.client_id = c.id
               JOIN admin_users u ON u.id = c.owner_account_id
               WHERE ci.instance_id = ?
               ORDER BY c.created_at DESC""",
            (instance_id,),
        )
        return [dict(row) for row in rows]

    def _affected_key_count(self, account_id: str, instance_id: str) -> int:
        rows = self.db.execute(
            """SELECT COUNT(*) AS count
               FROM api_clients c
               JOIN api_client_instances ci ON ci.client_id = c.id
               WHERE c.owner_account_id = ? AND ci.instance_id = ?""",
            (account_id, instance_id),
        )
        return int(rows[0]["count"]) if rows else 0

    def _delete_key_bindings(self, account_id: str, instance_id: str) -> None:
        self.db.execute(
            """DELETE FROM api_client_instances
               WHERE instance_id = ?
                 AND client_id IN (
                     SELECT id FROM api_clients WHERE owner_account_id = ?
                 )""",
            (instance_id, account_id),
        )

    def create_api_key(
        self,
        name: str,
        scope: str,
        instance_ids: list[str],
        owner_account_id: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Create an API key for one account."""
        owner_id = owner_account_id or self._admin_id()
        if not owner_id:
            raise ValueError("API key owner is required")
        owner = self.get_account(owner_id)
        if not owner["enabled"]:
            raise ValueError("Account is disabled")
        clean_name = name.strip()
        clean_scope = scope.strip()
        if not clean_name:
            raise ValueError("API key name is required")
        if clean_scope not in VALID_SCOPES:
            raise ValueError("Invalid API key scope")
        self._validate_api_key_instances(owner, instance_ids)
        raw_key = _generate_api_key()
        now = _now()
        client_id = f"ak_{uuid.uuid4().hex[:12]}"
        self.db.execute(
            """INSERT INTO api_clients
               (id, name, key_prefix, key_hash, scope, enabled,
                owner_account_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (
                client_id,
                clean_name,
                raw_key[:API_KEY_PREFIX_LENGTH],
                _hash_token(raw_key),
                clean_scope,
                owner_id,
                now,
                now,
            ),
        )
        self._replace_api_key_instances(client_id, instance_ids)
        return self.get_api_key(client_id), raw_key

    def list_api_keys(
        self,
        owner_account_id: str | None = None,
        *,
        include_all: bool = True,
    ) -> list[dict[str, Any]]:
        """List API keys according to caller visibility."""
        if include_all:
            rows = self.db.execute(
                """SELECT c.id, c.name, c.key_prefix, c.scope, c.enabled,
                          c.owner_account_id, u.username AS owner_username,
                          c.created_at, c.updated_at, c.last_used_at
                   FROM api_clients c
                   JOIN admin_users u ON u.id = c.owner_account_id
                   ORDER BY c.created_at DESC"""
            )
        else:
            rows = self.db.execute(
                """SELECT c.id, c.name, c.key_prefix, c.scope, c.enabled,
                          c.owner_account_id, u.username AS owner_username,
                          c.created_at, c.updated_at, c.last_used_at
                   FROM api_clients c
                   JOIN admin_users u ON u.id = c.owner_account_id
                   WHERE c.owner_account_id = ?
                   ORDER BY c.created_at DESC""",
                (owner_account_id,),
            )
        return [self._with_instances(row) for row in rows]

    def get_api_key(self, client_id: str) -> dict[str, Any]:
        """Return one API key with owner and bindings."""
        rows = self.db.execute(
            """SELECT c.id, c.name, c.key_prefix, c.scope, c.enabled,
                      c.owner_account_id, u.username AS owner_username,
                      c.created_at, c.updated_at, c.last_used_at
               FROM api_clients c
               JOIN admin_users u ON u.id = c.owner_account_id
               WHERE c.id = ? LIMIT 1""",
            (client_id,),
        )
        if not rows:
            raise ValueError("API key not found")
        return self._with_instances(rows[0])

    def can_manage_api_key(self, client_id: str, account_id: str, *, is_admin: bool) -> bool:
        """Return whether an actor can manage a key."""
        if is_admin:
            return True
        key = self.get_api_key(client_id)
        return key.get("owner_account_id") == account_id

    def update_api_key(
        self,
        client_id: str,
        *,
        name: str | None = None,
        scope: str | None = None,
        enabled: bool | None = None,
        instance_ids: list[str] | None = None,
        actor_id: str | None = None,
        is_admin: bool = True,
    ) -> dict[str, Any]:
        """Update API key metadata or bindings after ownership validation."""
        current = self.get_api_key(client_id)
        owner_id = current.get("owner_account_id")
        if not owner_id:
            raise ValueError("API key owner is required")
        if actor_id is not None and not self.can_manage_api_key(
            client_id,
            actor_id,
            is_admin=is_admin,
        ):
            raise ValueError("API key access denied")
        owner = self.get_account(owner_id)
        next_name = current["name"] if name is None else name.strip()
        next_scope = current["scope"] if scope is None else scope.strip()
        next_enabled = current["enabled"] if enabled is None else bool(enabled)
        if not owner["enabled"]:
            next_enabled = False
        if not next_name:
            raise ValueError("API key name is required")
        if next_scope not in VALID_SCOPES:
            raise ValueError("Invalid API key scope")
        if instance_ids is not None:
            self._validate_api_key_instances(self.get_account(owner_id), instance_ids)
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
        """Delete an API key."""
        self.get_api_key(client_id)
        self.db.execute("DELETE FROM api_clients WHERE id = ?", (client_id,))

    def rotate_api_key(self, client_id: str) -> tuple[dict[str, Any], str]:
        """Rotate an API key and return its new secret once."""
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
        """Resolve an API key into its effective account-scoped permissions."""
        key_hash = _hash_token(raw_key.strip())
        rows = self.db.execute(
            """SELECT c.id, c.name, c.scope, c.owner_account_id,
                      u.username, u.role, u.enabled
               FROM api_clients c
               JOIN admin_users u ON u.id = c.owner_account_id
               WHERE c.key_hash = ? AND c.enabled = 1
               LIMIT 1""",
            (key_hash,),
        )
        if not rows:
            return None
        row = rows[0]
        if not bool(row["enabled"]):
            return None
        instance_rows = self.db.execute(
            "SELECT instance_id FROM api_client_instances WHERE client_id = ?",
            (row["id"],),
        )
        if row["role"] == "admin":
            all_instances = self.db.execute("SELECT id FROM instances")
            account_permissions = {item["id"]: "edit" for item in all_instances}
        else:
            account_permissions = self._load_instance_permissions(row["owner_account_id"])
        effective: dict[str, str] = {}
        for item in instance_rows:
            instance_id = item["instance_id"]
            account_permission = account_permissions.get(instance_id)
            if not account_permission:
                continue
            effective[instance_id] = (
                "edit" if row["scope"] == "write" and account_permission == "edit" else "read"
            )
        self.db.execute(
            "UPDATE api_clients SET last_used_at = ? WHERE id = ?",
            (_now(), row["id"]),
        )
        return AuthContext(
            kind="api_key",
            user_id=row["owner_account_id"],
            username=row["username"],
            role=row["role"],
            enabled=True,
            client_id=row["id"],
            client_name=row["name"],
            scope=row["scope"],
            instance_ids=set(effective),
            instance_permissions=effective,
        )

    def _with_instances(self, row: dict[str, Any]) -> dict[str, Any]:
        instance_rows = self.db.execute(
            "SELECT instance_id FROM api_client_instances WHERE client_id = ? ORDER BY instance_id",
            (row["id"],),
        )
        result = dict(row)
        result["enabled"] = bool(result.get("enabled"))
        result["instance_ids"] = [item["instance_id"] for item in instance_rows]
        owner_id = result.get("owner_account_id")
        if owner_id:
            owner = self.get_account(owner_id)
            if owner["role"] == "admin":
                eligible_rows = self.db.execute("SELECT id FROM instances ORDER BY id")
                result["eligible_instance_ids"] = [row["id"] for row in eligible_rows]
            else:
                result["eligible_instance_ids"] = sorted(self._editable_instance_ids(owner_id))
        else:
            result["eligible_instance_ids"] = []
        return result

    def _replace_api_key_instances(self, client_id: str, instance_ids: list[str]) -> None:
        self.db.execute("DELETE FROM api_client_instances WHERE client_id = ?", (client_id,))
        unique_ids = list(dict.fromkeys(instance_ids))
        if unique_ids:
            self.db.executemany(
                "INSERT INTO api_client_instances (client_id, instance_id) VALUES (?, ?)",
                [(client_id, instance_id) for instance_id in unique_ids],
            )

    def _validate_api_key_instances(self, owner: dict[str, Any], instance_ids: list[str]) -> None:
        unique_ids = list(dict.fromkeys(instance_ids))
        if not unique_ids:
            return
        self._validate_instance_ids(unique_ids)
        if owner["role"] == "admin":
            return
        allowed = self._editable_instance_ids(owner["id"])
        disallowed = [instance_id for instance_id in unique_ids if instance_id not in allowed]
        if disallowed:
            raise ValueError("API key instance access is not allowed")

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


def _account_dict(row: dict[str, Any] | Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


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
