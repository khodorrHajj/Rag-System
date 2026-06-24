from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

class RetrievedChunk(BaseModel):
    chunk_id: UUID
    document_id: UUID
    user_id: UUID
    source_file: str
    chunk_index: int
    content: str
    page_number: int | None = None
    section_title: str | None = None
    subsection_title: str | None = None
    token_count: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    vector_score: float | None = None
    keyword_score: float | None = None
    combined_score: float = 0.0

class RetrievalDebugInfo(BaseModel):
    candidate_count: int
    vector_candidate_count: int
    keyword_candidate_count: int
    top_k: int
    candidate_k: int
    threshold: float | None = None
    latency_ms: int
    vector_weight: float
    keyword_weight: float
    document_filter_count: int = 0

class RetrievalResult(BaseModel):
    retrieval_passed: bool
    chunks: list[RetrievedChunk]
    debug: RetrievalDebugInfo

class RetrievalTestRequest(BaseModel):
    query: str
    document_ids: list[UUID] | None = None
    top_k: int | None = None
    candidate_k: int | None = None
    threshold: float | None = None

class RetrievalTestChunkResponse(BaseModel):
    chunk_id: UUID
    content_preview: str
    document_id: UUID
    source_file: str
    page_number: int | None = None
    section_title: str | None = None
    subsection_title: str | None = None
    chunk_index: int
    combined_score: float
    vector_score: float | None = None
    keyword_score: float | None = None

class RetrievalTestResponse(BaseModel):
    retrieval_passed: bool
    chunks: list[RetrievalTestChunkResponse]
    debug: RetrievalDebugInfo
