import logging
import time
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from redis import Redis as SyncRedis
from redis.exceptions import RedisError

from app.config import Settings, get_settings
from app.core.exceptions import AppError, DependencyUnavailableError
from app.core.redis import get_sync_redis_client
from app.services.audit_log_service import record_audit_log_sync
from app.services.chunk_artifact_service import delete_chunk_artifact, save_chunk_artifact
from app.services.chunking_service import chunk_parsed_document
from app.services.chunk_storage_service import store_document_chunks
from app.services.document_parser import parse_document_bytes
from app.services.document_service import (
    get_document_record_by_id,
    update_document_status,
)
from app.services.embedding_service import embed_texts
from app.services.job_queue_service import (
    enqueue_document_indexing_job_sync,
    parse_document_indexing_job_payload,
)
from app.services.parsed_artifact_service import delete_parsed_artifact, save_parsed_artifact
from app.services.storage_service import download_file

logger = logging.getLogger(__name__)
USER_INDEXING_LOCK_PREFIX = "lock:user:indexing"

def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return exc.detail

    return "Document processing failed."

def _failure_audit_action(processing_stage: str) -> str:
    if processing_stage == "parsing":
        return "parsing_failed"
    if processing_stage == "chunking":
        return "chunking_failed"

    return "indexing_failed"

def _user_indexing_lock_key(user_id: UUID) -> str:
    return f"{USER_INDEXING_LOCK_PREFIX}:{user_id}"

def _acquire_user_indexing_lock(
    redis_client: SyncRedis,
    *,
    user_id: UUID,
    document_id: UUID,
    settings: Settings,
) -> tuple[str, str] | None:
    lock_key = _user_indexing_lock_key(user_id)
    lock_token = str(uuid4())
    acquired = redis_client.set(
        lock_key,
        f"{lock_token}:{document_id}",
        nx=True,
        ex=settings.indexing_user_lock_ttl_seconds,
    )
    if not acquired:
        return None

    return lock_key, lock_token

def _release_user_indexing_lock(
    redis_client: SyncRedis,
    *,
    lock_key: str,
    lock_token: str,
) -> None:
    current_value = redis_client.get(lock_key)
    if current_value and current_value.startswith(f"{lock_token}:"):
        redis_client.delete(lock_key)

def _cleanup_processing_artifacts(document_row: dict[str, Any], settings: Settings) -> None:
    try:
        delete_parsed_artifact(
            user_id=document_row["user_id"],
            document_id=document_row["id"],
            settings=settings,
        )
    except DependencyUnavailableError:
        logger.warning(
            "Could not delete parsed artifact during cancellation cleanup for document_id=%s",
            document_row["id"],
            exc_info=True,
        )

    try:
        delete_chunk_artifact(
            user_id=document_row["user_id"],
            document_id=document_row["id"],
            settings=settings,
        )
    except DependencyUnavailableError:
        logger.warning(
            "Could not delete chunk artifact during cancellation cleanup for document_id=%s",
            document_row["id"],
            exc_info=True,
        )

def _latest_document_row(document_id: UUID) -> dict[str, Any] | None:
    return get_document_record_by_id(document_id)

def _document_is_deleted(document_row: dict[str, Any] | None) -> bool:
    return document_row is None or document_row.get("deleted_at") is not None or document_row.get("status") == "deleted"

def _stop_if_document_deleted(
    document_row: dict[str, Any],
    *,
    processing_stage: str,
    settings: Settings,
) -> bool:
    latest_document_row = _latest_document_row(document_row["id"])
    if not _document_is_deleted(latest_document_row):
        return False

    logger.info(
        "Stopping indexing for deleted document_id=%s at stage=%s",
        document_row["id"],
        processing_stage,
    )
    _cleanup_processing_artifacts(document_row, settings)
    return True

def _mark_document_failed(
    document_row: dict[str, Any],
    safe_message: str,
) -> None:
    update_document_status(
        document_id=document_row["id"],
        user_id=document_row["user_id"],
        status="failed",
        error_message=safe_message,
    )

def _schedule_retry(
    *,
    document_row: dict[str, Any],
    storage_path: str,
    attempt: int,
    max_attempts: int,
    safe_message: str,
) -> bool:
    try:
        enqueue_document_indexing_job_sync(
            document_id=document_row["id"],
            user_id=document_row["user_id"],
            storage_path=storage_path,
            attempt=attempt,
            max_attempts=max_attempts,
        )
    except DependencyUnavailableError:
        logger.exception(
            "Failed to re-enqueue retry for document_id=%s attempt=%s/%s",
            document_row["id"],
            attempt,
            max_attempts,
        )
        _mark_document_failed(document_row, "Document processing queue is temporarily unavailable.")
        record_audit_log_sync(
            action="indexing_failed",
            user_id=document_row["user_id"],
            resource_type="document",
            resource_id=document_row["id"],
            metadata={
                "attempt": attempt - 1,
                "max_attempts": max_attempts,
                "reason": "retry_enqueue_failed",
            },
        )
        return False

    update_document_status(
        document_id=document_row["id"],
        user_id=document_row["user_id"],
        status="queued",
        error_message=f"Retry scheduled after processing failure: {safe_message}",
    )
    record_audit_log_sync(
        action="indexing_retry_scheduled",
        user_id=document_row["user_id"],
        resource_type="document",
        resource_id=document_row["id"],
        metadata={
            "attempt": attempt,
            "max_attempts": max_attempts,
            "reason": safe_message,
        },
    )

    return False

def process_indexing_job_payload(payload: str | bytes, settings: Settings | None = None) -> bool:
    current_settings = settings or get_settings()
    job = parse_document_indexing_job_payload(payload)

    if job.job_type != "index_document":
        logger.warning("Skipping unsupported job_type=%s", job.job_type)
        return False

    document_row = get_document_record_by_id(job.document_id)
    if document_row is None:
        logger.warning("Skipping indexing job because document_id=%s no longer exists.", job.document_id)
        return False

    if str(document_row["user_id"]) != str(job.user_id):
        logger.error(
            "Indexing job ownership mismatch for document_id=%s expected_user_id=%s job_user_id=%s",
            job.document_id,
            document_row["user_id"],
            job.user_id,
        )
        _mark_document_failed(document_row, "Document ownership validation failed during indexing.")
        record_audit_log_sync(
            action="indexing_failed",
            user_id=document_row["user_id"],
            resource_type="document",
            resource_id=document_row["id"],
            metadata={
                "reason": "ownership_mismatch",
                "attempt": job.attempt,
            },
        )
        return False

    if document_row["deleted_at"] is not None or document_row["status"] == "deleted":
        logger.info("Skipping indexing for deleted document_id=%s", job.document_id)
        return False

    if document_row["storage_path"] != job.storage_path:
        logger.warning(
            "Indexing job storage path mismatch for document_id=%s db_storage_path=%s job_storage_path=%s",
            job.document_id,
            document_row["storage_path"],
            job.storage_path,
        )

    update_document_status(
        document_id=document_row["id"],
        user_id=document_row["user_id"],
        status="processing",
        error_message=None,
    )
    record_audit_log_sync(
        action="indexing_started",
        user_id=document_row["user_id"],
        resource_type="document",
        resource_id=document_row["id"],
        metadata={
            "attempt": job.attempt,
            "max_attempts": job.max_attempts,
            "storage_path": document_row["storage_path"],
        },
    )

    processing_stage = "parsing"
    started_at = perf_counter()

    try:
        file_bytes = download_file(document_row["storage_path"])
        if _stop_if_document_deleted(document_row, processing_stage=processing_stage, settings=current_settings):
            return False
        parser_name, units = parse_document_bytes(document_row, file_bytes, settings=current_settings)
        artifact_path = save_parsed_artifact(
            document_id=document_row["id"],
            user_id=document_row["user_id"],
            file_type=document_row["file_type"],
            parser=parser_name,
            units=units,
            settings=current_settings,
        )
        if _stop_if_document_deleted(document_row, processing_stage=processing_stage, settings=current_settings):
            return False
        update_document_status(
            document_id=document_row["id"],
            user_id=document_row["user_id"],
            status="parsed",
            error_message=None,
        )
        record_audit_log_sync(
            action="parsing_succeeded",
            user_id=document_row["user_id"],
            resource_type="document",
            resource_id=document_row["id"],
            metadata={
                "attempt": job.attempt,
                "parser": parser_name,
                "unit_count": len(units),
                "artifact_path": artifact_path,
            },
        )
        processing_stage = "chunking"
        record_audit_log_sync(
            action="chunking_started",
            user_id=document_row["user_id"],
            resource_type="document",
            resource_id=document_row["id"],
            metadata={
                "attempt": job.attempt,
                "parser": parser_name,
                "unit_count": len(units),
            },
        )
        chunks = chunk_parsed_document(
            units,
            document_row["id"],
            document_row["user_id"],
            config=current_settings,
        )
        if not chunks:
            raise AppError("Document did not produce any chunks for indexing.", status_code=400)

        chunk_artifact_path = save_chunk_artifact(
            document_id=document_row["id"],
            user_id=document_row["user_id"],
            chunks=chunks,
            settings=current_settings,
        )
        if _stop_if_document_deleted(document_row, processing_stage=processing_stage, settings=current_settings):
            return False
        update_document_status(
            document_id=document_row["id"],
            user_id=document_row["user_id"],
            status="chunked",
            error_message=None,
        )
        record_audit_log_sync(
            action="chunking_succeeded",
            user_id=document_row["user_id"],
            resource_type="document",
            resource_id=document_row["id"],
            metadata={
                "attempt": job.attempt,
                "chunk_count": len(chunks),
                "artifact_path": chunk_artifact_path,
            },
        )
        processing_stage = "embedding"
        chunk_embeddings = embed_texts(
            [chunk.content for chunk in chunks],
            settings=current_settings,
        )
        if _stop_if_document_deleted(document_row, processing_stage=processing_stage, settings=current_settings):
            return False
        record_audit_log_sync(
            action="embedding_succeeded",
            user_id=document_row["user_id"],
            resource_type="document",
            resource_id=document_row["id"],
            metadata={
                "attempt": job.attempt,
                "chunk_count": len(chunks),
                "embedding_model": current_settings.embedding_model_name,
                "embedding_dimension": current_settings.embedding_dimension,
            },
        )
        processing_stage = "storage"
        stored_chunk_count = store_document_chunks(
            document_row=document_row,
            chunks=chunks,
            embeddings=chunk_embeddings,
            settings=current_settings,
        )
        if _stop_if_document_deleted(document_row, processing_stage=processing_stage, settings=current_settings):
            return False
        logger.info(
            "Processed document_id=%s parser=%s unit_count=%s chunk_count=%s model=%s dimension=%s",
            job.document_id,
            parser_name,
            len(units),
            len(chunks),
            current_settings.embedding_model_name,
            current_settings.embedding_dimension,
        )
        update_document_status(
            document_id=document_row["id"],
            user_id=document_row["user_id"],
            status="indexed",
            error_message=None,
        )
        duration_ms = round((perf_counter() - started_at) * 1000)
        record_audit_log_sync(
            action="indexing_succeeded",
            user_id=document_row["user_id"],
            resource_type="document",
            resource_id=document_row["id"],
            metadata={
                "attempt": job.attempt,
                "parser": parser_name,
                "unit_count": len(units),
                "chunk_count": stored_chunk_count,
                "embedding_model": current_settings.embedding_model_name,
                "embedding_dimension": current_settings.embedding_dimension,
                "duration_ms": duration_ms,
            },
        )

        return True
    except (AppError, DependencyUnavailableError) as exc:
        safe_message = _safe_error_message(exc)
        logger.warning(
            "Document processing failed for document_id=%s stage=%s attempt=%s/%s: %s",
            job.document_id,
            processing_stage,
            job.attempt,
            job.max_attempts,
            safe_message,
        )
        if _stop_if_document_deleted(document_row, processing_stage=processing_stage, settings=current_settings):
            return False
        record_audit_log_sync(
            action=_failure_audit_action(processing_stage),
            user_id=document_row["user_id"],
            resource_type="document",
            resource_id=document_row["id"],
            metadata={
                "attempt": job.attempt,
                "max_attempts": job.max_attempts,
                "stage": processing_stage,
                "reason": safe_message,
            },
        )

        if job.attempt < job.max_attempts:
            return _schedule_retry(
                document_row=document_row,
                storage_path=document_row["storage_path"],
                attempt=job.attempt + 1,
                max_attempts=job.max_attempts,
                safe_message=safe_message,
            )

        _mark_document_failed(document_row, safe_message)
        record_audit_log_sync(
            action="indexing_failed",
            user_id=document_row["user_id"],
            resource_type="document",
            resource_id=document_row["id"],
            metadata={
                "attempt": job.attempt,
                "max_attempts": job.max_attempts,
                "stage": processing_stage,
                "reason": safe_message,
            },
        )
        return False
    except Exception as exc:
        safe_message = _safe_error_message(exc)
        logger.exception(
            "Unexpected indexing failure for document_id=%s attempt=%s/%s",
            job.document_id,
            job.attempt,
            job.max_attempts,
        )
        if _stop_if_document_deleted(document_row, processing_stage=processing_stage, settings=current_settings):
            return False

        if job.attempt < job.max_attempts:
            return _schedule_retry(
                document_row=document_row,
                storage_path=document_row["storage_path"],
                attempt=job.attempt + 1,
                max_attempts=job.max_attempts,
                safe_message="Document processing failed.",
            )

        _mark_document_failed(document_row, "Document processing failed.")
        record_audit_log_sync(
            action="indexing_failed",
            user_id=document_row["user_id"],
            resource_type="document",
            resource_id=document_row["id"],
            metadata={
                "attempt": job.attempt,
                "max_attempts": job.max_attempts,
                "stage": processing_stage,
                "reason": safe_message,
            },
        )
        return False

def process_next_job_once(
    *,
    block_timeout_seconds: int | None = None,
    settings: Settings | None = None,
) -> bool:
    current_settings = settings or get_settings()
    redis_client = get_sync_redis_client(current_settings)
    lock_key: str | None = None
    lock_token: str | None = None

    try:
        result = redis_client.blpop(
            current_settings.document_queue_name,
            timeout=block_timeout_seconds
            if block_timeout_seconds is not None
            else current_settings.indexing_queue_block_timeout_seconds,
        )
    except RedisError as exc:
        logger.exception("Worker could not read from Redis queue.")
        raise DependencyUnavailableError("Document processing queue is temporarily unavailable.") from exc

    if result is None:
        redis_client.close()
        return False

    _, payload = result
    try:
        job = parse_document_indexing_job_payload(payload)
    except Exception:
        logger.exception("Worker could not parse an indexing job payload; dropping job.")
        redis_client.close()
        return False

    acquired_lock = _acquire_user_indexing_lock(
        redis_client,
        user_id=job.user_id,
        document_id=job.document_id,
        settings=current_settings,
    )
    if acquired_lock is None:
        logger.info(
            "Re-queueing document_id=%s because user_id=%s already has an active indexing job.",
            job.document_id,
            job.user_id,
        )
        redis_client.rpush(current_settings.document_queue_name, payload)
        redis_client.close()
        return False

    lock_key, lock_token = acquired_lock
    try:
        return process_indexing_job_payload(payload, settings=current_settings)
    finally:
        try:
            _release_user_indexing_lock(
                redis_client,
                lock_key=lock_key,
                lock_token=lock_token,
            )
        finally:
            redis_client.close()

def run_worker_forever() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    logger.info(
        "Starting index worker for queue=%s with max_attempts=%s",
        settings.document_queue_name,
        settings.indexing_max_attempts,
    )

    while True:
        try:
            processed = process_next_job_once(settings=settings)
            if not processed:
                time.sleep(0.25)
        except DependencyUnavailableError:
            logger.warning("Worker queue dependency is unavailable; retrying shortly.")
            time.sleep(2)
        except Exception:
            logger.exception("Worker encountered an unexpected top-level error; retrying shortly.")
            time.sleep(2)

if __name__ == "__main__":
    run_worker_forever()
