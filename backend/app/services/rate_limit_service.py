from dataclasses import dataclass
from uuid import UUID

from fastapi import Request
from redis.exceptions import RedisError

from app.core.client_ip import get_client_ip
from app.core.exceptions import DependencyUnavailableError, RateLimitExceededError
from app.core.redis import ensure_redis_available
from app.schemas.auth import CurrentUser

@dataclass(frozen=True)
class RateLimitRule:
    key_template: str
    limit: int
    window_seconds: int

@dataclass(frozen=True)
class RateLimitStatus:
    key: str
    limit: int
    remaining: int
    reset_in_seconds: int

RATE_LIMIT_RULES: dict[str, dict[str, RateLimitRule]] = {
    "chat": {
        "ip": RateLimitRule("rate:ip:chat:{ip}", limit=60, window_seconds=60),
        "user": RateLimitRule("rate:user:chat:{user_id}", limit=120, window_seconds=60),
    },
    "retrieval": {
        "ip": RateLimitRule("rate:ip:retrieval:{ip}", limit=60, window_seconds=60),
        "user": RateLimitRule("rate:user:retrieval:{user_id}", limit=120, window_seconds=60),
    },
    "upload": {
        "ip": RateLimitRule("rate:ip:upload:{ip}", limit=20, window_seconds=60),
        "user": RateLimitRule("rate:user:upload:{user_id}", limit=30, window_seconds=60),
    },
    "indexing": {
        "user": RateLimitRule("rate:user:indexing:{user_id}", limit=10, window_seconds=60),
    },
}

async def _consume_limit(key: str, limit: int, window_seconds: int) -> RateLimitStatus:
    client = await ensure_redis_available()

    try:
        current_count = await client.incr(key)
        if current_count == 1:
            await client.expire(key, window_seconds)

        ttl_seconds = await client.ttl(key)
    except RedisError as exc:
        raise DependencyUnavailableError(
            "Rate limiting service is temporarily unavailable."
        ) from exc
    finally:
        await client.aclose()

    if ttl_seconds < 0:
        ttl_seconds = window_seconds

    remaining = max(limit - current_count, 0)
    if current_count > limit:
        raise RateLimitExceededError(
            "Rate limit exceeded. Please try again later.",
            retry_after_seconds=ttl_seconds,
        )

    return RateLimitStatus(
        key=key,
        limit=limit,
        remaining=remaining,
        reset_in_seconds=ttl_seconds,
    )

async def check_ip_limit(scope: str, ip_address: str) -> RateLimitStatus:
    rule = RATE_LIMIT_RULES[scope]["ip"]
    key = rule.key_template.format(ip=ip_address)

    return await _consume_limit(key, rule.limit, rule.window_seconds)

async def check_user_limit(scope: str, user_id: str | UUID) -> RateLimitStatus:
    rule = RATE_LIMIT_RULES[scope]["user"]
    key = rule.key_template.format(user_id=user_id)

    return await _consume_limit(key, rule.limit, rule.window_seconds)

async def enforce_limits_for_request(
    request: Request,
    current_user: CurrentUser,
    *,
    scope: str,
) -> dict[str, RateLimitStatus]:
    ip_address = get_client_ip(request)
    statuses: dict[str, RateLimitStatus] = {}

    if "ip" in RATE_LIMIT_RULES[scope]:
        statuses["ip"] = await check_ip_limit(scope, ip_address)

    if "user" in RATE_LIMIT_RULES[scope]:
        statuses["user"] = await check_user_limit(scope, current_user.user_id)

    return statuses

async def enforce_chat_limits(
    request: Request,
    current_user: CurrentUser,
) -> dict[str, RateLimitStatus]:
    return await enforce_limits_for_request(request, current_user, scope="chat")

async def enforce_retrieval_limits(
    request: Request,
    current_user: CurrentUser,
) -> dict[str, RateLimitStatus]:
    return await enforce_limits_for_request(request, current_user, scope="retrieval")

async def enforce_upload_limits(
    request: Request,
    current_user: CurrentUser,
) -> dict[str, RateLimitStatus]:
    return await enforce_limits_for_request(request, current_user, scope="upload")

async def enforce_indexing_limits(
    request: Request,
    current_user: CurrentUser,
) -> dict[str, RateLimitStatus]:
    return await enforce_limits_for_request(request, current_user, scope="indexing")
