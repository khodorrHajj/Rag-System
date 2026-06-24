from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

class EvaluationCase(BaseModel):
    case_name: str | None = None
    question: str
    document_ids: list[UUID] | None = None
    expected_answer_contains: list[str] = Field(default_factory=list)
    expected_source_file: str | None = None
    expected_page_number: int | None = None

class EvaluationRunRequest(BaseModel):
    run_all: bool = True
    case_name: str | None = None
    case: EvaluationCase | None = None

class EvaluationResultRecord(BaseModel):
    result_id: UUID
    run_id: UUID
    case_name: str | None = None
    question: str
    document_ids: list[UUID] = Field(default_factory=list)
    retrieval_passed: bool
    retrieved_source_match: bool
    expected_terms_found: dict[str, bool] = Field(default_factory=dict)
    expected_terms_passed: bool
    answer_generated: bool
    citations_present: bool
    latency_ms: int
    expected_source_file: str | None = None
    expected_page_number: int | None = None
    answer_preview: str | None = None
    created_at: datetime

class EvaluationRunResponse(BaseModel):
    run_id: UUID
    run_mode: str
    case_count: int
    passed_count: int
    created_at: datetime
    results: list[EvaluationResultRecord]

class EvaluationResultsListResponse(BaseModel):
    runs: list[EvaluationRunResponse]

class StoredEvaluationRun(BaseModel):
    run_id: UUID
    run_mode: str
    case_count: int
    passed_count: int
    created_at: datetime
    triggered_by_user_id: UUID | None = None
    results: list[EvaluationResultRecord] = Field(default_factory=list)

class EvaluationCaseFile(BaseModel):
    file_name: str
    cases: list[EvaluationCase]

class EvaluationExecutionPayload(BaseModel):
    retrieval_passed: bool
    retrieved_source_match: bool
    expected_terms_found: dict[str, bool]
    expected_terms_passed: bool
    answer_generated: bool
    citations_present: bool
    latency_ms: int
    answer_preview: str | None = None
    retrieval_debug: dict[str, Any] = Field(default_factory=dict)
