import logging
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

from app.config import Settings, get_settings
from app.core.database import database_connection
from app.core.exceptions import AppError, DependencyUnavailableError, RequestEntityTooLargeError

logger = logging.getLogger(__name__)

SUPPORTED_MIME_TYPES: dict[str, set[str]] = {
    "pdf": {"application/pdf"},
}
GENERIC_MIME_TYPES = {"application/octet-stream", "binary/octet-stream"}

def sanitize_original_filename(filename: str | None) -> str:
    if not filename:
        raise AppError("A file must be provided.", status_code=400)

    cleaned_name = Path(filename).name.strip()
    if not cleaned_name:
        raise AppError("A file must be provided.", status_code=400)

    return cleaned_name

def validate_upload_file(
    *,
    filename: str,
    content_type: str | None,
    file_size_bytes: int,
    settings: Settings | None = None,
) -> dict[str, str]:
    current_settings = settings or get_settings()
    sanitized_filename = sanitize_original_filename(filename)
    extension = Path(sanitized_filename).suffix.lower().lstrip(".")

    if not extension:
        raise AppError(
            "Uploaded files must include a supported file extension.",
            status_code=400,
        )

    if extension == "doc":
        raise AppError(
            "Legacy .doc files are not supported. Please upload a PDF file.",
            status_code=400,
        )

    if extension not in current_settings.allowed_upload_extensions:
        raise AppError(
            "Only .pdf files are supported.",
            status_code=400,
        )

    if file_size_bytes <= 0:
        raise AppError("Uploaded files cannot be empty.", status_code=400)

    if file_size_bytes > current_settings.max_upload_size_bytes:
        raise RequestEntityTooLargeError(
            f"Uploaded file exceeds the maximum allowed size of {current_settings.max_upload_size_mb} MB."
        )

    normalized_content_type = (content_type or "").split(";")[0].strip().lower()
    if (
        normalized_content_type
        and normalized_content_type not in GENERIC_MIME_TYPES
        and normalized_content_type not in SUPPORTED_MIME_TYPES.get(extension, set())
    ):
        raise AppError(
            "Uploaded file type does not match its extension.",
            status_code=400,
        )

    resolved_content_type = normalized_content_type or {
        "pdf": "application/pdf",
    }[extension]

    return {
        "extension": extension,
        "content_type": resolved_content_type,
        "original_filename": sanitized_filename,
    }

def build_storage_path(user_id: UUID, document_id: UUID, extension: str) -> dict[str, str]:
    safe_filename = f"original.{extension}"
    storage_path = f"uploads/{user_id}/{document_id}/{safe_filename}"

    return {
        "safe_filename": safe_filename,
        "storage_path": storage_path,
    }

def _serialize_document_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": row["id"],
        "original_filename": row["original_filename"],
        "safe_filename": row["safe_filename"],
        "file_type": row["file_type"],
        "file_size_bytes": row["file_size_bytes"],
        "status": row["status"],
        "error_message": row.get("error_message"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "deleted_at": row.get("deleted_at"),
    }

def _run_db_operation(operation_name: str, callback):
    try:
        return callback()
    except psycopg.Error as exc:
        logger.exception("Database operation failed during %s", operation_name)
        raise DependencyUnavailableError("Database service is temporarily unavailable.") from exc

def build_document_limit_message(max_documents_per_user: int) -> str:
    return (
        f"You can keep up to {max_documents_per_user} active files. "
        "Delete one before adding another."
    )

def create_document_record(
    *,
    document_id: UUID,
    user_id: UUID,
    original_filename: str,
    safe_filename: str,
    file_type: str,
    storage_path: str,
    file_size_bytes: int,
    status: str,
    error_message: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    current_settings = settings or get_settings()

    def callback() -> dict[str, Any]:
        with database_connection(current_settings) as connection:
            with connection.cursor() as cursor:
                
                
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (str(user_id),),
                )
                cursor.execute(
                    """
                    SELECT COUNT(*)::int AS document_count
                    FROM public.documents
                    WHERE user_id = %s
                      AND deleted_at IS NULL
                    """,
                    (user_id,),
                )
                active_document_count = int(cursor.fetchone()["document_count"])
                if active_document_count >= current_settings.max_documents_per_user:
                    raise AppError(
                        build_document_limit_message(current_settings.max_documents_per_user),
                        status_code=409,
                    )

                cursor.execute(
                    """
                    INSERT INTO public.documents (
                        id,
                        user_id,
                        original_filename,
                        safe_filename,
                        file_type,
                        storage_path,
                        file_size_bytes,
                        status,
                        error_message
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        document_id,
                        user_id,
                        original_filename,
                        safe_filename,
                        file_type,
                        storage_path,
                        file_size_bytes,
                        status,
                        error_message,
                    ),
                )
                row = cursor.fetchone()
                cursor.execute(
                    """
                    INSERT INTO public.document_permissions (
                        document_id,
                        owner_user_id,
                        permitted_user_id,
                        permission_level
                    )
                    VALUES (%s, %s, NULL, 'owner')
                    """,
                    (document_id, user_id),
                )
            connection.commit()

        return row

    return _run_db_operation("create_document_record", callback)

def update_document_status(
    *,
    document_id: UUID,
    user_id: UUID,
    status: str,
    error_message: str | None = None,
) -> dict[str, Any] | None:
    def callback() -> dict[str, Any] | None:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE public.documents
                    SET
                        status = %s,
                        error_message = %s,
                        updated_at = timezone('utc', now())
                    WHERE id = %s
                      AND user_id = %s
                      AND deleted_at IS NULL
                    RETURNING *
                    """,
                    (status, error_message, document_id, user_id),
                )
                row = cursor.fetchone()
            connection.commit()

        return row

    return _run_db_operation("update_document_status", callback)

def list_documents_for_user(user_id: UUID, *, include_deleted: bool = False) -> list[dict[str, Any]]:
    def callback() -> list[dict[str, Any]]:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                if include_deleted:
                    cursor.execute(
                        """
                        SELECT *
                        FROM public.documents
                        WHERE user_id = %s
                        ORDER BY created_at DESC
                        """,
                        (user_id,),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT *
                        FROM public.documents
                        WHERE user_id = %s
                          AND deleted_at IS NULL
                        ORDER BY created_at DESC
                        """,
                        (user_id,),
                    )
                rows = cursor.fetchall()

        return [_serialize_document_row(row) for row in rows]

    return _run_db_operation("list_documents_for_user", callback)

def count_active_documents_for_user(user_id: UUID) -> int:
    def callback() -> int:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)::int AS document_count
                    FROM public.documents
                    WHERE user_id = %s
                      AND deleted_at IS NULL
                    """,
                    (user_id,),
                )
                row = cursor.fetchone()

        return int(row["document_count"]) if row else 0

    return _run_db_operation("count_active_documents_for_user", callback)

def get_document_for_user(document_id: UUID, user_id: UUID) -> dict[str, Any] | None:
    def callback() -> dict[str, Any] | None:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT d.*
                    FROM public.documents AS d
                    WHERE d.id = %s
                      AND d.deleted_at IS NULL
                      AND (
                        d.user_id = %s
                        OR EXISTS (
                            SELECT 1
                            FROM public.document_permissions AS dp
                            WHERE dp.document_id = d.id
                              AND dp.permitted_user_id = %s
                              AND dp.permission_level = 'read'
                        )
                      )
                    LIMIT 1
                    """,
                    (document_id, user_id, user_id),
                )
                row = cursor.fetchone()

        return _serialize_document_row(row) if row else None

    return _run_db_operation("get_document_for_user", callback)

def get_owned_document_record(document_id: UUID, user_id: UUID) -> dict[str, Any] | None:
    def callback() -> dict[str, Any] | None:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM public.documents
                    WHERE id = %s
                      AND user_id = %s
                      AND deleted_at IS NULL
                    LIMIT 1
                    """,
                    (document_id, user_id),
                )
                row = cursor.fetchone()

        return row

    return _run_db_operation("get_owned_document_record", callback)

def get_document_record_by_id(document_id: UUID) -> dict[str, Any] | None:
    def callback() -> dict[str, Any] | None:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM public.documents
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (document_id,),
                )
                row = cursor.fetchone()

        return row

    return _run_db_operation("get_document_record_by_id", callback)

def soft_delete_document(document_id: UUID, user_id: UUID) -> dict[str, Any] | None:
    def callback() -> dict[str, Any] | None:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE public.documents
                    SET
                        status = 'deleted',
                        deleted_at = timezone('utc', now()),
                        updated_at = timezone('utc', now()),
                        error_message = NULL
                    WHERE id = %s
                      AND user_id = %s
                      AND deleted_at IS NULL
                    RETURNING *
                    """,
                    (document_id, user_id),
                )
                row = cursor.fetchone()
            connection.commit()

        return row

    return _run_db_operation("soft_delete_document", callback)
