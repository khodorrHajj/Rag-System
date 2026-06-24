from __future__ import annotations

import logging
from typing import Any

import psycopg

from app.config import Settings, get_settings
from app.core.database import database_connection
from app.core.exceptions import DependencyUnavailableError
from app.schemas.admin import DeveloperDashboardResponse, DeveloperMetrics, RecentAuditLog, RecentRetrievalLog
from app.schemas.evaluation import EvaluationRunResponse
from app.schemas.feedback import FeedbackRecord
from app.services.evaluation_service import list_evaluation_runs
from app.services.feedback_service import list_feedback

logger = logging.getLogger(__name__)

def _run_db_operation(operation_name: str, callback):
    try:
        return callback()
    except psycopg.Error as exc:
        logger.exception("Database operation failed during %s", operation_name)
        raise DependencyUnavailableError("Database service is temporarily unavailable.") from exc

def get_developer_dashboard(
    settings: Settings | None = None,
) -> DeveloperDashboardResponse:
    current_settings = settings or get_settings()

    def callback() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        with database_connection(current_settings) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM public.documents WHERE status = 'indexed' AND deleted_at IS NULL) AS indexed_documents,
                        (SELECT COUNT(*) FROM public.document_chunks) AS total_chunks,
                        (SELECT COUNT(*) FROM public.audit_logs WHERE action = 'retrieval_failed_low_confidence') AS low_confidence_retrievals,
                        (SELECT COUNT(*) FROM public.documents WHERE status = 'failed' AND deleted_at IS NULL) AS failed_indexing_jobs,
                        (SELECT COUNT(*) FROM public.feedback WHERE rating = 'positive') AS positive_feedback,
                        (SELECT COUNT(*) FROM public.feedback WHERE rating = 'negative') AS negative_feedback,
                        (SELECT AVG(latency_ms)::float FROM public.retrieval_logs WHERE latency_ms IS NOT NULL) AS average_retrieval_latency_ms,
                        (SELECT COUNT(*) FROM public.audit_logs WHERE action = 'model_fallback_used') AS model_fallback_count
                    """
                )
                metrics_row = cursor.fetchone()

                cursor.execute(
                    """
                    SELECT
                        rl.id,
                        rl.user_id,
                        p.email AS user_email,
                        rl.query,
                        rl.original_question,
                        rl.top_k,
                        rl.threshold,
                        rl.latency_ms,
                        jsonb_array_length(COALESCE(rl.retrieved_chunk_ids, '[]'::jsonb)) AS retrieved_chunk_count,
                        rl.created_at
                    FROM public.retrieval_logs AS rl
                    LEFT JOIN public.profiles AS p
                      ON p.id = rl.user_id
                    ORDER BY rl.created_at DESC
                    LIMIT %s
                    """,
                    (current_settings.observability_recent_limit,),
                )
                retrieval_rows = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT
                        al.id,
                        al.user_id,
                        p.email AS user_email,
                        al.action,
                        al.resource_type,
                        al.resource_id,
                        al.metadata,
                        al.ip_address,
                        al.created_at
                    FROM public.audit_logs AS al
                    LEFT JOIN public.profiles AS p
                      ON p.id = al.user_id
                    ORDER BY al.created_at DESC
                    LIMIT %s
                    """,
                    (current_settings.observability_recent_limit,),
                )
                audit_rows = cursor.fetchall()

        return metrics_row, retrieval_rows, audit_rows

    metrics_row, retrieval_rows, audit_rows = _run_db_operation("get_developer_dashboard", callback)
    recent_feedback: list[FeedbackRecord] = list_feedback(
        current_user_id=None,
        include_all=True,
        settings=current_settings,
    )
    recent_evaluations: list[EvaluationRunResponse] = list_evaluation_runs(settings=current_settings)

    return DeveloperDashboardResponse(
        metrics=DeveloperMetrics(
            indexed_documents=metrics_row["indexed_documents"],
            total_chunks=metrics_row["total_chunks"],
            low_confidence_retrievals=metrics_row["low_confidence_retrievals"],
            failed_indexing_jobs=metrics_row["failed_indexing_jobs"],
            positive_feedback=metrics_row["positive_feedback"],
            negative_feedback=metrics_row["negative_feedback"],
            average_retrieval_latency_ms=metrics_row["average_retrieval_latency_ms"],
            model_fallback_count=metrics_row["model_fallback_count"],
        ),
        recent_retrieval_logs=[
            RecentRetrievalLog(
                log_id=row["id"],
                user_id=row["user_id"],
                user_email=row.get("user_email"),
                query=row["query"],
                original_question=row.get("original_question"),
                top_k=row["top_k"],
                threshold=float(row["threshold"]) if row["threshold"] is not None else None,
                latency_ms=row.get("latency_ms"),
                retrieved_chunk_count=row["retrieved_chunk_count"],
                created_at=row["created_at"],
            )
            for row in retrieval_rows
        ],
        recent_audit_logs=[
            RecentAuditLog(
                log_id=row["id"],
                user_id=row.get("user_id"),
                user_email=row.get("user_email"),
                action=row["action"],
                resource_type=row.get("resource_type"),
                resource_id=row.get("resource_id"),
                metadata=row.get("metadata") or {},
                ip_address=row.get("ip_address"),
                created_at=row["created_at"],
            )
            for row in audit_rows
        ],
        recent_feedback=recent_feedback,
        recent_evaluations=recent_evaluations,
    )
