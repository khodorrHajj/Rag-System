from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from app.config import Settings, get_settings
from app.core.database import database_connection
from app.core.exceptions import AppError, DependencyUnavailableError
from app.schemas.ingestion import ChunkCandidate

logger = logging.getLogger(__name__)
VECTOR_TYPE_RE = re.compile(r"vector\((\d+)\)")

def _run_db_operation(operation_name: str, callback):
    try:
        return callback()
    except AppError:
        raise
    except psycopg.Error as exc:
        logger.exception("Database operation failed during %s", operation_name)
        raise DependencyUnavailableError("Database service is temporarily unavailable.") from exc

def _validate_chunks_and_embeddings(
    *,
    document_row: dict,
    chunks: list[ChunkCandidate],
    embeddings: list[list[float]],
    settings: Settings,
) -> None:
    if document_row["deleted_at"] is not None or document_row["status"] in {"deleted", "failed"}:
        raise AppError("Document is not eligible for chunk storage.", status_code=400)

    if not chunks:
        raise AppError("Document did not produce any chunks to store.", status_code=400)

    if len(chunks) != len(embeddings):
        raise AppError("Chunk and embedding counts do not match.", status_code=400)

    expected_user_id = str(document_row["user_id"])
    expected_document_id = str(document_row["id"])

    for chunk, embedding in zip(chunks, embeddings, strict=True):
        if str(chunk.user_id) != expected_user_id:
            raise AppError("Chunk ownership did not match the document owner.", status_code=400)
        if str(chunk.document_id) != expected_document_id:
            raise AppError("Chunk document ID did not match the target document.", status_code=400)
        if len(embedding) != settings.embedding_dimension:
            raise AppError(
                "Embedding dimension did not match the configured pgvector dimension.",
                status_code=500,
            )

def _get_live_embedding_dimension(cursor) -> int | None:
    cursor.execute(
        """
        SELECT pg_catalog.format_type(a.atttypid, a.atttypmod) AS type_name
        FROM pg_catalog.pg_attribute AS a
        JOIN pg_catalog.pg_class AS c
          ON c.oid = a.attrelid
        JOIN pg_catalog.pg_namespace AS n
          ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname = 'document_chunks'
          AND a.attname = 'embedding'
          AND a.attnum > 0
          AND NOT a.attisdropped
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    if not row:
        return None

    type_name = row["type_name"]
    if not isinstance(type_name, str):
        return None

    match = VECTOR_TYPE_RE.fullmatch(type_name)
    if not match:
        return None

    return int(match.group(1))

def store_document_chunks(
    *,
    document_row: dict,
    chunks: list[ChunkCandidate],
    embeddings: list[list[float]],
    settings: Settings | None = None,
) -> int:
    current_settings = settings or get_settings()
    _validate_chunks_and_embeddings(
        document_row=document_row,
        chunks=chunks,
        embeddings=embeddings,
        settings=current_settings,
    )

    def callback() -> int:
        created_at = datetime.now(timezone.utc)
        with database_connection(current_settings) as connection:
            with connection.cursor() as cursor:
                live_dimension = _get_live_embedding_dimension(cursor)
                if live_dimension != current_settings.embedding_dimension:
                    raise AppError(
                        "Database embedding dimension does not match the configured embedding model.",
                        status_code=500,
                    )

                cursor.execute(
                    """
                    DELETE FROM public.document_chunks
                    WHERE document_id = %s
                      AND user_id = %s
                    """,
                    (document_row["id"], document_row["user_id"]),
                )

                insert_rows = [
                    (
                        uuid4(),
                        chunk.document_id,
                        chunk.user_id,
                        chunk.chunk_index,
                        chunk.content,
                        embedding,
                        chunk.page_number,
                        chunk.section_title,
                        chunk.subsection_title,
                        chunk.token_count,
                        Jsonb(chunk.metadata),
                        created_at,
                    )
                    for chunk, embedding in zip(chunks, embeddings, strict=True)
                ]

                cursor.executemany(
                    """
                    INSERT INTO public.document_chunks (
                        id,
                        document_id,
                        user_id,
                        chunk_index,
                        content,
                        embedding,
                        page_number,
                        section_title,
                        subsection_title,
                        token_count,
                        metadata,
                        created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    insert_rows,
                )
            connection.commit()

        return len(insert_rows)

    stored_count = _run_db_operation("store_document_chunks", callback)
    logger.info(
        "Stored chunk embeddings document_id=%s user_id=%s chunk_count=%s dimension=%s",
        document_row["id"],
        document_row["user_id"],
        stored_count,
        current_settings.embedding_dimension,
    )

    return stored_count

def list_document_chunk_previews(
    *,
    document_id: UUID,
    user_id: UUID,
    preview_chars: int = 160,
) -> list[dict]:
    safe_preview_chars = max(preview_chars, 40)

    def callback() -> list[dict]:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        document_id,
                        user_id,
                        chunk_index,
                        LEFT(content, %s) AS content_preview,
                        page_number,
                        section_title,
                        subsection_title,
                        token_count,
                        metadata,
                        created_at
                    FROM public.document_chunks
                    WHERE document_id = %s
                      AND user_id = %s
                    ORDER BY chunk_index ASC
                    """,
                    (safe_preview_chars, document_id, user_id),
                )
                return cursor.fetchall()

    return _run_db_operation("list_document_chunk_previews", callback)
