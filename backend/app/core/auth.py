from __future__ import annotations

import json
import logging
from threading import Lock
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen
from uuid import UUID

import jwt
from fastapi import Depends, Request, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import (
    ExpiredSignatureError,
    ImmatureSignatureError,
    InvalidAudienceError,
    InvalidIssuedAtError,
    InvalidIssuerError,
    InvalidSignatureError,
    InvalidTokenError,
    MissingRequiredClaimError,
    PyJWTError,
)
from jwt.algorithms import get_default_algorithms

from app.config import Settings, get_settings
from app.core.exceptions import AuthenticationError
from app.schemas.auth import CurrentUser
from app.services.profile_service import ensure_profile_for_current_user
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)

AUTHENTICATION_REQUIRED_MESSAGE = "Authentication required."
INVALID_TOKEN_MESSAGE = "Invalid or expired authentication token."
JWKS_CACHE_TTL_SECONDS = 300
SUPPORTED_JWKS_ALGORITHMS = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}
SUPPORTED_HMAC_ALGORITHMS = {"HS256", "HS384", "HS512"}

class _JwksCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._fetched_at = 0.0
        self._keys_by_kid: dict[str, dict[str, Any]] = {}

    def get(self) -> tuple[float, dict[str, dict[str, Any]]]:
        with self._lock:
            return self._fetched_at, dict(self._keys_by_kid)

    def set(self, keys_by_kid: dict[str, dict[str, Any]]) -> None:
        with self._lock:
            self._fetched_at = time.time()
            self._keys_by_kid = dict(keys_by_kid)

    def clear(self) -> None:
        with self._lock:
            self._fetched_at = 0.0
            self._keys_by_kid = {}

_jwks_cache = _JwksCache()

def clear_jwks_cache() -> None:
    _jwks_cache.clear()

def extract_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError(AUTHENTICATION_REQUIRED_MESSAGE)

    token = credentials.credentials.strip()
    if not token:
        raise AuthenticationError(AUTHENTICATION_REQUIRED_MESSAGE)

    return token

def _extract_websocket_bearer_token(websocket: WebSocket) -> str:
    authorization = websocket.headers.get("authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token

    token = (websocket.query_params.get("token") or "").strip()
    if token:
        return token

    raise AuthenticationError(AUTHENTICATION_REQUIRED_MESSAGE)

def _fetch_jwks_payload(jwks_url: str) -> dict[str, Any]:
    try:
        with urlopen(jwks_url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Supabase JWKS fetch failed for url=%s", jwks_url, exc_info=True)
        raise AuthenticationError(INVALID_TOKEN_MESSAGE) from exc

    if not isinstance(payload, dict):
        logger.warning("Supabase JWKS payload was not a JSON object.")
        raise AuthenticationError(INVALID_TOKEN_MESSAGE)

    return payload

def _normalize_jwks_payload(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    keys = payload.get("keys")
    if not isinstance(keys, list):
        logger.warning("Supabase JWKS payload did not contain a valid keys array.")
        raise AuthenticationError(INVALID_TOKEN_MESSAGE)

    keys_by_kid: dict[str, dict[str, Any]] = {}
    for key_entry in keys:
        if not isinstance(key_entry, dict):
            continue

        kid = key_entry.get("kid")
        if isinstance(kid, str) and kid:
            keys_by_kid[kid] = key_entry

    if not keys_by_kid:
        logger.warning("Supabase JWKS payload did not contain any usable keys.")
        raise AuthenticationError(INVALID_TOKEN_MESSAGE)

    return keys_by_kid

def _get_cached_jwks_keys(settings: Settings, *, force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    jwks_url = settings.resolved_supabase_jwks_url
    if not jwks_url:
        logger.warning("JWT verification failed because no Supabase JWKS URL is configured.")
        raise AuthenticationError(INVALID_TOKEN_MESSAGE)

    fetched_at, cached_keys = _jwks_cache.get()
    is_fresh = (time.time() - fetched_at) < JWKS_CACHE_TTL_SECONDS
    if cached_keys and is_fresh and not force_refresh:
        return cached_keys

    payload = _fetch_jwks_payload(jwks_url)
    keys_by_kid = _normalize_jwks_payload(payload)
    _jwks_cache.set(keys_by_kid)

    return keys_by_kid

def _resolve_jwk_for_kid(kid: str, settings: Settings) -> dict[str, Any]:
    keys_by_kid = _get_cached_jwks_keys(settings)
    key = keys_by_kid.get(kid)
    if key is not None:
        return key

    keys_by_kid = _get_cached_jwks_keys(settings, force_refresh=True)
    key = keys_by_kid.get(kid)
    if key is not None:
        return key

    logger.warning("JWT verification failed because no matching JWKS key was found for kid=%s", kid)
    raise AuthenticationError(INVALID_TOKEN_MESSAGE)

def _jwt_decode_options(settings: Settings) -> dict[str, Any]:
    return {
        "require": ["exp", "sub"],
        "verify_signature": True,
        "verify_exp": True,
        "verify_iat": True,
        "verify_nbf": True,
        "verify_aud": True,
        "verify_iss": settings.resolved_supabase_jwt_issuer is not None,
    }

def _validate_role(payload: dict[str, Any]) -> str | None:
    role = payload.get("role")
    if role is None:
        return None

    if not isinstance(role, str):
        logger.warning("JWT verification failed because role was not a string.")
        raise AuthenticationError(INVALID_TOKEN_MESSAGE)

    if role != "authenticated":
        logger.warning("JWT verification failed because role=%s is not allowed for user routes.", role)
        raise AuthenticationError(INVALID_TOKEN_MESSAGE)

    return role

def _is_admin_email(email: str | None, settings: Settings) -> bool:
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return False

    return normalized_email in settings.admin_emails

def _can_access_developer_tools(email: str | None, settings: Settings) -> bool:
    return _is_admin_email(email, settings)

def _extract_current_user(payload: dict[str, Any], settings: Settings) -> CurrentUser:
    subject = payload.get("sub")
    if not isinstance(subject, str):
        logger.warning("JWT verification failed because subject claim was missing or invalid.")
        raise AuthenticationError(INVALID_TOKEN_MESSAGE)

    try:
        user_id = UUID(subject)
    except ValueError as exc:
        logger.warning("JWT verification failed because subject claim was not a UUID.")
        raise AuthenticationError(INVALID_TOKEN_MESSAGE) from exc

    email = payload.get("email")
    if email is not None and not isinstance(email, str):
        logger.warning("Ignoring non-string email claim for subject %s", user_id)
        email = None

    role = _validate_role(payload)
    is_admin = _is_admin_email(email, settings)
    can_access_developer_tools = _can_access_developer_tools(email, settings)

    return CurrentUser(
        user_id=user_id,
        email=email,
        role=role,
        is_admin=is_admin,
        can_access_developer_tools=can_access_developer_tools,
    )

def _decode_with_jwks(
    token: str,
    *,
    header: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    algorithm = header.get("alg")
    if not isinstance(algorithm, str) or algorithm not in SUPPORTED_JWKS_ALGORITHMS:
        logger.warning("JWT verification failed because alg=%s is not supported for JWKS verification.", algorithm)
        raise AuthenticationError(INVALID_TOKEN_MESSAGE)

    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        logger.warning("JWT verification failed because the token header did not include a kid.")
        raise AuthenticationError(INVALID_TOKEN_MESSAGE)

    jwk = _resolve_jwk_for_kid(kid, settings)

    try:
        algorithm_impl = get_default_algorithms()[algorithm]
        public_key = algorithm_impl.from_jwk(json.dumps(jwk))
    except (KeyError, InvalidTokenError, ValueError) as exc:
        logger.warning("JWT verification failed because the JWKS key for kid=%s could not be loaded.", kid)
        raise AuthenticationError(INVALID_TOKEN_MESSAGE) from exc

    try:
        return jwt.decode(
            token,
            key=public_key,
            algorithms=[algorithm],
            audience=settings.resolved_supabase_jwt_audience,
            issuer=settings.resolved_supabase_jwt_issuer,
            options=_jwt_decode_options(settings),
        )
    except (
        ExpiredSignatureError,
        ImmatureSignatureError,
        InvalidAudienceError,
        InvalidIssuedAtError,
        InvalidIssuerError,
        InvalidSignatureError,
        MissingRequiredClaimError,
        PyJWTError,
    ) as exc:
        logger.warning(
            "JWT verification failed for JWKS-verified token with kid=%s because %s",
            kid,
            exc.__class__.__name__,
        )
        raise AuthenticationError(INVALID_TOKEN_MESSAGE) from exc

def _decode_with_legacy_secret(
    token: str,
    *,
    header: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    algorithm = header.get("alg")
    if not isinstance(algorithm, str) or algorithm not in SUPPORTED_HMAC_ALGORITHMS:
        logger.warning(
            "JWT verification failed because alg=%s is not supported for legacy secret verification.",
            algorithm,
        )
        raise AuthenticationError(INVALID_TOKEN_MESSAGE)

    if not settings.supabase_jwt_secret:
        logger.warning("JWT verification failed because no legacy Supabase JWT secret is configured.")
        raise AuthenticationError(INVALID_TOKEN_MESSAGE)

    try:
        return jwt.decode(
            token,
            key=settings.supabase_jwt_secret,
            algorithms=[algorithm],
            audience=settings.resolved_supabase_jwt_audience,
            issuer=settings.resolved_supabase_jwt_issuer,
            options=_jwt_decode_options(settings),
        )
    except (
        ExpiredSignatureError,
        ImmatureSignatureError,
        InvalidAudienceError,
        InvalidIssuedAtError,
        InvalidIssuerError,
        InvalidSignatureError,
        MissingRequiredClaimError,
        PyJWTError,
    ) as exc:
        logger.warning(
            "JWT verification failed for legacy-secret token because %s",
            exc.__class__.__name__,
        )
        raise AuthenticationError(INVALID_TOKEN_MESSAGE) from exc

def verify_supabase_jwt(token: str, settings: Settings | None = None) -> CurrentUser:
    current_settings = settings or get_settings()
    if current_settings.auth_allow_unverified_jwt:
        logger.warning(
            "AUTH_ALLOW_UNVERIFIED_JWT is enabled, but protected routes still require verified JWTs."
        )

    try:
        header = jwt.get_unverified_header(token)
    except PyJWTError as exc:
        logger.warning("JWT verification failed because the token header could not be parsed.")
        raise AuthenticationError(INVALID_TOKEN_MESSAGE) from exc

    algorithm = header.get("alg")
    if not isinstance(algorithm, str) or algorithm.lower() == "none":
        logger.warning("JWT verification failed because unsigned tokens are not allowed.")
        raise AuthenticationError(INVALID_TOKEN_MESSAGE)

    if current_settings.resolved_supabase_jwks_url and algorithm in SUPPORTED_JWKS_ALGORITHMS:
        payload = _decode_with_jwks(token, header=header, settings=current_settings)
        return _extract_current_user(payload, current_settings)

    if current_settings.supabase_jwt_secret and algorithm in SUPPORTED_HMAC_ALGORITHMS:
        payload = _decode_with_legacy_secret(token, header=header, settings=current_settings)
        return _extract_current_user(payload, current_settings)

    logger.warning(
        "JWT verification failed because no trusted verifier was available for algorithm=%s",
        algorithm,
    )
    raise AuthenticationError(INVALID_TOKEN_MESSAGE)

async def get_current_user(
    request: Request,
    token: str = Depends(extract_bearer_token),
) -> CurrentUser:
    current_user = verify_supabase_jwt(token)
    await run_in_threadpool(ensure_profile_for_current_user, current_user)
    request.state.private_response = True
    request.state.current_user_id = str(current_user.user_id)

    return current_user

async def get_current_user_from_websocket(websocket: WebSocket) -> CurrentUser:
    token = _extract_websocket_bearer_token(websocket)
    current_user = verify_supabase_jwt(token)
    await run_in_threadpool(ensure_profile_for_current_user, current_user)
    return current_user
