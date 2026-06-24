import hashlib
import hmac
import json
import logging
import time
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import httpx

from app.config import Settings, get_settings
from app.core.exceptions import AppError, DependencyUnavailableError

logger = logging.getLogger(__name__)
SUPPORTED_STORAGE_BACKENDS = {"local", "supabase"}

def _normalize_storage_path(storage_path: str) -> PurePosixPath:
    normalized_path = PurePosixPath(storage_path)

    if normalized_path.is_absolute() or ".." in normalized_path.parts:
        raise AppError("Invalid storage path.", status_code=400)

    return normalized_path

def _local_root(settings: Settings) -> Path:
    root = Path(settings.storage_local_root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    return root

def _resolve_local_file_path(storage_path: str, settings: Settings) -> Path:
    relative_path = _normalize_storage_path(storage_path)

    return _local_root(settings).joinpath(*relative_path.parts)

def _resolve_local_metadata_path(file_path: Path) -> Path:
    return file_path.with_suffix(f"{file_path.suffix}.metadata.json")

def _resolved_storage_backend(settings: Settings) -> str:
    return settings.storage_backend.strip().lower()

def _ensure_supported_backend(settings: Settings) -> None:
    if _resolved_storage_backend(settings) in SUPPORTED_STORAGE_BACKENDS:
        return

    logger.error(
        "Storage backend '%s' is configured but not implemented in the current scaffold.",
        settings.storage_backend,
    )
    raise DependencyUnavailableError("Storage service is temporarily unavailable.")

def _supabase_storage_base_url(settings: Settings) -> str:
    if not settings.supabase_url:
        logger.error("Supabase Storage backend requires SUPABASE_URL.")
        raise DependencyUnavailableError("Storage service is temporarily unavailable.")

    return f"{settings.supabase_url.rstrip('/')}/storage/v1"

def _supabase_service_key(settings: Settings) -> str:
    service_key = settings.resolved_supabase_service_key
    if service_key:
        return service_key

    logger.error("Supabase Storage backend requires a backend-only service key.")
    raise DependencyUnavailableError("Storage service is temporarily unavailable.")

def _supabase_headers(
    settings: Settings,
    *,
    content_type: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    service_key = _supabase_service_key(settings)
    headers = {
        "Authorization": f"Bearer {service_key}",
        "apikey": service_key,
    }
    if content_type:
        headers["Content-Type"] = content_type
    if extra_headers:
        headers.update(extra_headers)

    return headers

def _supabase_object_path(storage_path: str) -> str:
    return quote(_normalize_storage_path(storage_path).as_posix(), safe="/")

def _supabase_object_url(storage_path: str, settings: Settings) -> str:
    return (
        f"{_supabase_storage_base_url(settings)}/object/"
        f"{settings.storage_bucket_name}/{_supabase_object_path(storage_path)}"
    )

def _supabase_request(
    method: str,
    url: str,
    *,
    settings: Settings,
    expected_status_codes: set[int],
    content_type: str | None = None,
    content: bytes | None = None,
    json_body: dict[str, object] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    headers = _supabase_headers(
        settings,
        content_type=content_type,
        extra_headers=extra_headers,
    )

    try:
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=True) as client:
            response = client.request(
                method,
                url,
                headers=headers,
                content=content,
                json=json_body,
            )
    except httpx.HTTPError as exc:
        logger.exception("Supabase Storage request failed for %s %s", method, url)
        raise DependencyUnavailableError("Storage service is temporarily unavailable.") from exc

    if response.status_code in expected_status_codes:
        return response

    if response.status_code == 404:
        raise AppError("Stored file not found.", status_code=404)

    logger.error(
        "Supabase Storage request returned status=%s for %s %s response=%s",
        response.status_code,
        method,
        url,
        response.text[:500],
    )
    raise DependencyUnavailableError("Storage service is temporarily unavailable.")

def upload_file(
    storage_path: str,
    file_bytes: bytes,
    content_type: str,
    settings: Settings | None = None,
) -> None:
    current_settings = settings or get_settings()
    _ensure_supported_backend(current_settings)

    if _resolved_storage_backend(current_settings) == "local":
        file_path = _resolve_local_file_path(storage_path, current_settings)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(file_bytes)
        _resolve_local_metadata_path(file_path).write_text(
            json.dumps({"content_type": content_type}),
            encoding="utf-8",
        )
        return

    _supabase_request(
        "POST",
        _supabase_object_url(storage_path, current_settings),
        settings=current_settings,
        expected_status_codes={200},
        content_type=content_type,
        content=file_bytes,
        extra_headers={"x-upsert": "true"},
    )

def download_file(storage_path: str, settings: Settings | None = None) -> bytes:
    current_settings = settings or get_settings()
    _ensure_supported_backend(current_settings)

    if _resolved_storage_backend(current_settings) == "local":
        file_path = _resolve_local_file_path(storage_path, current_settings)
        if not file_path.exists():
            raise AppError("Stored file not found.", status_code=404)

        return file_path.read_bytes()

    response = _supabase_request(
        "GET",
        _supabase_object_url(storage_path, current_settings),
        settings=current_settings,
        expected_status_codes={200},
    )

    return response.content

def delete_file(storage_path: str, settings: Settings | None = None) -> bool:
    current_settings = settings or get_settings()
    _ensure_supported_backend(current_settings)

    if _resolved_storage_backend(current_settings) == "local":
        file_path = _resolve_local_file_path(storage_path, current_settings)
        metadata_path = _resolve_local_metadata_path(file_path)
        deleted = False

        if file_path.exists():
            file_path.unlink()
            deleted = True

        if metadata_path.exists():
            metadata_path.unlink()

        return deleted

    try:
        _supabase_request(
            "DELETE",
            _supabase_object_url(storage_path, current_settings),
            settings=current_settings,
            expected_status_codes={200, 204},
        )
    except AppError as exc:
        if exc.status_code == 404:
            return False
        raise

    return True

def generate_signed_download_url(
    storage_path: str,
    expires_in_seconds: int,
    settings: Settings | None = None,
) -> str:
    current_settings = settings or get_settings()
    _ensure_supported_backend(current_settings)

    expires_at = int(time.time()) + max(expires_in_seconds, 1)
    normalized_storage_path = _normalize_storage_path(storage_path).as_posix()
    payload = f"{current_settings.storage_bucket_name}:{normalized_storage_path}:{expires_at}"
    signature = hmac.new(
        current_settings.storage_signed_url_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if _resolved_storage_backend(current_settings) == "local":
        return (
            f"local-private://{current_settings.storage_bucket_name}/{normalized_storage_path}"
            f"?expires_at={expires_at}&signature={signature}"
        )

    response = _supabase_request(
        "POST",
        (
            f"{_supabase_storage_base_url(current_settings)}/object/sign/"
            f"{current_settings.storage_bucket_name}/{_supabase_object_path(storage_path)}"
        ),
        settings=current_settings,
        expected_status_codes={200},
        content_type="application/json",
        json_body={"expiresIn": max(expires_in_seconds, 1), "download": True},
    )
    payload = response.json()
    signed_url = payload.get("signedURL") or payload.get("signedUrl")
    if not isinstance(signed_url, str) or not signed_url:
        logger.error("Supabase Storage signed URL response was missing a signed URL.")
        raise DependencyUnavailableError("Storage service is temporarily unavailable.")

    if signed_url.startswith("http://") or signed_url.startswith("https://"):
        return signed_url

    if signed_url.startswith("/"):
        return f"{current_settings.supabase_url.rstrip('/')}{signed_url}"

    return f"{_supabase_storage_base_url(current_settings)}/{signed_url.lstrip('/')}"
