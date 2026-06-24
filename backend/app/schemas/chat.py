from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.retrieval import RetrievalDebugInfo

class ChatSessionCreateRequest(BaseModel):
    title: str | None = None

class ChatSessionSummary(BaseModel):
    session_id: UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime

class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionSummary]

class ChatSessionDeleteResponse(BaseModel):
    session_id: UUID
    deleted: bool

class ChatSource(BaseModel):
    source_number: int
    chunk_id: UUID
    document_id: UUID
    source_file: str
    page_number: int | None = None
    section_title: str | None = None
    subsection_title: str | None = None
    chunk_index: int
    score: float

class ChatDebugChunk(BaseModel):
    chunk_id: UUID
    document_id: UUID
    source_file: str
    section_title: str | None = None
    subsection_title: str | None = None
    combined_score: float
    vector_score: float | None = None
    keyword_score: float | None = None
    content_preview: str

class ChatDebugInfo(BaseModel):
    original_question: str
    retrieval_query: str
    history_used_for_rewrite: bool
    retrieval: RetrievalDebugInfo
    chunks: list[ChatDebugChunk]

class ChatRequest(BaseModel):
    session_id: UUID | None = None
    question: str
    document_ids: list[UUID] | None = None
    debug: bool = False

class ChatResponse(BaseModel):
    session_id: UUID
    answer: str
    sources: list[ChatSource]
    model_used: str | None = None
    retrieval_passed: bool
    user_message: "ChatMessageRecord | None" = None
    assistant_message: "ChatMessageRecord | None" = None
    debug: ChatDebugInfo | None = None

class ChatMessageCitation(BaseModel):
    source_number: int
    chunk_id: UUID
    document_id: UUID
    source_file: str
    page_number: int | None = None
    section_title: str | None = None
    similarity_score: float | None = None

class ChatMessageRecord(BaseModel):
    message_id: UUID
    session_id: UUID
    role: str
    content: str
    model_used: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    estimated_cost: float | None = None
    created_at: datetime
    citations: list[ChatMessageCitation] = Field(default_factory=list)

class ChatMessageListResponse(BaseModel):
    session_id: UUID
    messages: list[ChatMessageRecord]

class LLMUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

class LLMResponse(BaseModel):
    answer: str
    model_used: str
    usage: LLMUsage = Field(default_factory=LLMUsage)
    fallback_used: bool = False
    raw_response_metadata: dict[str, Any] = Field(default_factory=dict)
