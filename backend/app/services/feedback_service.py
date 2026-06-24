from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

import psycopg

from app.config import Settings, get_settings
from app.core.database import database_connection
from app.core.exceptions import AppError, DependencyUnavailableError, NotFoundError
from app.schemas.feedback import FeedbackRecord

logger = logging.getLogger(__name__)

def _run_db_operation(operation_name: str, callback):
    try:
        return callback()
    except AppError:
        raise
    except psycopg.Error as exc:
        logger.exception("Database operation failed during %s", operation_name)
        raise DependencyUnavailableError("Database service is temporarily unavailable.") from exc

def _serialize_feedback_row(row: dict[str, Any]) -> FeedbackRecord:
    return FeedbackRecord(
        feedback_id=row["id"],
        user_id=row["user_id"],
        message_id=row["message_id"],
        rating=row["rating"],
        comment=row.get("comment"),
        created_at=row["created_at"],
        user_email=row.get("user_email"),
    )

def submit_feedback(
    *,
    current_user_id: UUID,
    message_id: UUID,
    rating: str,
    comment: str | None = None,
    allow_cross_user: bool = False,
    settings: Settings | None = None,
) -> FeedbackRecord:
    current_settings = settings or get_settings()
    cleaned_comment = comment.strip() if comment else None
    if cleaned_comment == "":
        cleaned_comment = None

    if len(cleaned_comment or "") > current_settings.feedback_comment_max_length:
        raise AppError(
            f"Feedback comments may be at most {current_settings.feedback_comment_max_length} characters long.",
            status_code=400,
        )

    if rating not in {"positive", "negative"}:
        raise AppError("Feedback rating must be either positive or negative.", status_code=400)

    def callback() -> dict[str, Any]:
        with database_connection(current_settings) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, role
                    FROM public.chat_messages
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (message_id,),
                )
                message_row = cursor.fetchone()
                if message_row is None:
                    raise NotFoundError("Message not found.")

                if message_row["role"] != "assistant":
                    raise AppError("Feedback can only be attached to assistant messages.", status_code=400)

                if not allow_cross_user and message_row["user_id"] != current_user_id:
                    raise NotFoundError("Message not found.")

                cursor.execute(
                    """
                    INSERT INTO public.feedback (
                        id,
                        user_id,
                        message_id,
                        rating,
                        comment
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, message_id)
                    DO UPDATE
                    SET rating = EXCLUDED.rating,
                        comment = EXCLUDED.comment,
                        created_at = timezone('utc', now())
                    RETURNING id, user_id, message_id, rating, comment, created_at
                    """,
                    (uuid4(), current_user_id, message_id, rating, cleaned_comment),
                )
                feedback_row = cursor.fetchone()
            connection.commit()

        feedback_row["user_email"] = None
        return feedback_row

    row = _run_db_operation("submit_feedback", callback)
    return _serialize_feedback_row(row)

def list_feedback(
    *,
    current_user_id: UUID | None,
    include_all: bool = False,
    settings: Settings | None = None,
) -> list[FeedbackRecord]:
    current_settings = settings or get_settings()

    def callback() -> list[dict[str, Any]]:
        with database_connection(current_settings) as connection:
            with connection.cursor() as cursor:
                if include_all:
                    cursor.execute(
                        """
                        SELECT
                            f.id,
                            f.user_id,
                            f.message_id,
                            f.rating,
                            f.comment,
                            f.created_at,
                            p.email AS user_email
                        FROM public.feedback AS f
                        LEFT JOIN public.profiles AS p
                          ON p.id = f.user_id
                        ORDER BY f.created_at DESC
                        LIMIT %s
                        """,
                        (current_settings.observability_recent_limit,),
                    )
                else:
                    if current_user_id is None:
                        return []
                    cursor.execute(
                        """
                        SELECT
                            f.id,
                            f.user_id,
                            f.message_id,
                            f.rating,
                            f.comment,
                            f.created_at,
                            p.email AS user_email
                        FROM public.feedback AS f
                        LEFT JOIN public.profiles AS p
                          ON p.id = f.user_id
                        WHERE f.user_id = %s
                        ORDER BY f.created_at DESC
                        """,
                        (current_user_id,),
                    )
                return cursor.fetchall()

    rows = _run_db_operation("list_feedback", callback)
    return [_serialize_feedback_row(row) for row in rows]
