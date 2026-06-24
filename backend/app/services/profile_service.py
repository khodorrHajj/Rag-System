from __future__ import annotations

import logging
import time

import psycopg

from app.core.database import database_connection, database_is_configured
from app.core.exceptions import DependencyUnavailableError
from app.schemas.auth import CurrentUser

logger = logging.getLogger(__name__)
PROFILE_SYNC_TTL_SECONDS = 300
_profile_sync_cache: dict[str, float] = {}

def _build_profile_cache_key(current_user: CurrentUser) -> str | None:
    if not current_user.email:
        return None

    return f"{current_user.user_id}:{current_user.email.strip().lower()}"

def _prune_profile_sync_cache(now: float) -> None:
    expired_keys = [
        cache_key
        for cache_key, synced_at in _profile_sync_cache.items()
        if now - synced_at >= PROFILE_SYNC_TTL_SECONDS
    ]
    for cache_key in expired_keys:
        _profile_sync_cache.pop(cache_key, None)

def ensure_profile_for_current_user(current_user: CurrentUser) -> None:
    if not database_is_configured():
        return

    if not current_user.email:
        logger.debug("Skipping profile sync because the verified token did not include an email.")
        return

    now = time.monotonic()
    _prune_profile_sync_cache(now)
    cache_key = _build_profile_cache_key(current_user)
    if cache_key and now - _profile_sync_cache.get(cache_key, 0.0) < PROFILE_SYNC_TTL_SECONDS:
        return

    try:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO public.profiles (
                        id,
                        email,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, timezone('utc', now()), timezone('utc', now()))
                    ON CONFLICT (id) DO UPDATE
                    SET email = EXCLUDED.email,
                        updated_at = timezone('utc', now())
                    WHERE public.profiles.email IS DISTINCT FROM EXCLUDED.email
                    """,
                    (current_user.user_id, current_user.email),
                )
            connection.commit()
        if cache_key:
            _profile_sync_cache[cache_key] = now
    except psycopg.Error as exc:
        logger.exception(
            "Profile synchronization failed for verified user_id=%s",
            current_user.user_id,
        )
        raise DependencyUnavailableError("Database service is temporarily unavailable.") from exc
