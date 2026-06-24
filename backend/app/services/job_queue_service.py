import json
import logging
from uuid import UUID

from redis import Redis as SyncRedis
from redis.exceptions import RedisError

from app.config import get_settings
from app.core.exceptions import DependencyUnavailableError
from app.core.redis import ensure_redis_available, get_sync_redis_client
from app.schemas.ingestion import DocumentIndexingJob

logger = logging.getLogger(__name__)

def build_document_indexing_job(
    *,
    document_id: UUID,
    user_id: UUID,
    storage_path: str,
    attempt: int = 1,
    max_attempts: int | None = None,
) -> DocumentIndexingJob:
    settings = get_settings()

    return DocumentIndexingJob(
        document_id=document_id,
        user_id=user_id,
        storage_path=storage_path,
        attempt=attempt,
        max_attempts=max_attempts or settings.indexing_max_attempts,
    )

def parse_document_indexing_job_payload(payload: str | bytes) -> DocumentIndexingJob:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")

    return DocumentIndexingJob.model_validate_json(payload)

async def enqueue_document_indexing_job(
    document_id: UUID,
    user_id: UUID,
    storage_path: str,
    *,
    attempt: int = 1,
    max_attempts: int | None = None,
) -> dict[str, str | int]:
    settings = get_settings()
    client = await ensure_redis_available()
    job = build_document_indexing_job(
        document_id=document_id,
        user_id=user_id,
        storage_path=storage_path,
        attempt=attempt,
        max_attempts=max_attempts,
    )
    payload = job.model_dump(mode="json")

    try:
        await client.rpush(settings.document_queue_name, json.dumps(payload))
    except RedisError as exc:
        logger.warning(
            "Failed to enqueue indexing job for document_id=%s user_id=%s",
            document_id,
            user_id,
        )
        raise DependencyUnavailableError(
            "Document processing queue is temporarily unavailable."
        ) from exc
    finally:
        await client.aclose()

    return payload

def enqueue_document_indexing_job_sync(
    document_id: UUID,
    user_id: UUID,
    storage_path: str,
    *,
    attempt: int = 1,
    max_attempts: int | None = None,
    client: SyncRedis | None = None,
) -> dict[str, str | int]:
    settings = get_settings()
    current_client = client or get_sync_redis_client()
    job = build_document_indexing_job(
        document_id=document_id,
        user_id=user_id,
        storage_path=storage_path,
        attempt=attempt,
        max_attempts=max_attempts,
    )
    payload = job.model_dump(mode="json")

    try:
        current_client.rpush(settings.document_queue_name, json.dumps(payload))
    except RedisError as exc:
        logger.warning(
            "Failed to enqueue indexing job synchronously for document_id=%s user_id=%s",
            document_id,
            user_id,
        )
        raise DependencyUnavailableError(
            "Document processing queue is temporarily unavailable."
        ) from exc

    return payload
