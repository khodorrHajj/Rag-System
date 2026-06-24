from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.evaluation import EvaluationRunResponse
from app.schemas.feedback import FeedbackRecord

class DeveloperMetrics(BaseModel):
    indexed_documents: int
    total_chunks: int
    low_confidence_retrievals: int
    failed_indexing_jobs: int
    positive_feedback: int
    negative_feedback: int
    average_retrieval_latency_ms: float | None = None
    model_fallback_count: int

class RecentRetrievalLog(BaseModel):
    log_id: UUID
    user_id: UUID
    user_email: str | None = None
    query: str
    original_question: str | None = None
    top_k: int
    threshold: float | None = None
    latency_ms: int | None = None
    retrieved_chunk_count: int
    created_at: datetime

class RecentAuditLog(BaseModel):
    log_id: UUID
    user_id: UUID | None = None
    user_email: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    ip_address: str | None = None
    created_at: datetime

class DeveloperDashboardResponse(BaseModel):
    metrics: DeveloperMetrics
    recent_retrieval_logs: list[RecentRetrievalLog]
    recent_audit_logs: list[RecentAuditLog]
    recent_feedback: list[FeedbackRecord]
    recent_evaluations: list[EvaluationRunResponse]
