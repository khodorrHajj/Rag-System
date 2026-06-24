import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from starlette.concurrency import run_in_threadpool

from app.core.database import database_connection
from app.core.exceptions import DependencyUnavailableError

logger = logging.getLogger(__name__)
MAX_AUDIT_STRING_LENGTH = 500
REDACTED = "[redacted]"
SENSITIVE_KEY_FRAGMENTS = (
    "token",
    "secret",
    "password",
    "authorization",
    "api_key",
    "service_role",
    "jwt",
)
BLOCKED_VALUE_KEYS = {
    "embedding",
    "embeddings",
    "vector",
    "database_url",
    "redis_url",
}

@dataclass(frozen=True)
class AuditLogEntry:
    action: str
    user_id: UUID | None = None
    resource_type: str | None = None
    resource_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    ip_address: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

async def record_audit_log(
    *,
    action: str,
    user_id: UUID | None = None,
    resource_type: str | None = None,
    resource_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLogEntry:
    return await run_in_threadpool(
        record_audit_log_sync,
        action=action,
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata=metadata,
        ip_address=ip_address,
    )

def record_audit_log_sync(
    *,
    action: str,
    user_id: UUID | None = None,
    resource_type: str | None = None,
    resource_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLogEntry:
    sanitized_metadata = _sanitize_metadata(metadata or {})
    entry = AuditLogEntry(
        action=action,
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata=sanitized_metadata,
        ip_address=ip_address,
    )

    try:
        _persist_audit_log(entry)
    except psycopg.Error as exc:
        logger.exception(
            "Failed to persist audit log action=%s user_id=%s resource_id=%s",
            action,
            user_id,
            resource_id,
        )
        raise DependencyUnavailableError("Database service is temporarily unavailable.") from exc

    logger.info(
        "Audit log recorded action=%s user_id=%s resource_type=%s resource_id=%s ip_address=%s",
        entry.action,
        entry.user_id,
        entry.resource_type,
        entry.resource_id,
        entry.ip_address,
    )
    return entry

def _persist_audit_log(entry: AuditLogEntry) -> None:
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.audit_logs (
                    id,
                    user_id,
                    action,
                    resource_type,
                    resource_id,
                    metadata,
                    ip_address,
                    created_at
                )
                VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    entry.user_id,
                    entry.action,
                    entry.resource_type,
                    entry.resource_id,
                    Jsonb(entry.metadata),
                    entry.ip_address,
                    entry.created_at,
                ),
            )
        connection.commit()

def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): _sanitize_value(str(key), value)
        for key, value in metadata.items()
    }

def _sanitize_value(key: str, value: Any) -> Any:
    normalized_key = key.strip().lower()
    if normalized_key in BLOCKED_VALUE_KEYS or any(
        fragment in normalized_key for fragment in SENSITIVE_KEY_FRAGMENTS
    ):
        return REDACTED

    if isinstance(value, dict):
        return {
            str(child_key): _sanitize_value(str(child_key), child_value)
            for child_key, child_value in value.items()
        }

    if isinstance(value, list):
        return [_sanitize_value(key, item) for item in value[:50]]

    if isinstance(value, tuple):
        return [_sanitize_value(key, item) for item in list(value)[:50]]

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, str):
        if len(value) <= MAX_AUDIT_STRING_LENGTH:
            return value
        return f"{value[:MAX_AUDIT_STRING_LENGTH].rstrip()}..."

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    return str(value)

def serialize_audit_log_entry(entry: AuditLogEntry) -> dict[str, Any]:
    return asdict(entry)
