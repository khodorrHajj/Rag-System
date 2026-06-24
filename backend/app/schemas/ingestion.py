from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

class ParsedDocumentUnit(BaseModel):
    text: str
    page_number: int | None = None
    section_title: str | None = None
    subsection_title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class ParsedDocumentArtifact(BaseModel):
    document_id: UUID
    user_id: UUID
    file_type: str
    parser: str
    unit_count: int
    created_at: datetime
    units: list[ParsedDocumentUnit]

class ChunkCandidate(BaseModel):
    document_id: UUID
    user_id: UUID
    chunk_index: int
    content: str
    page_number: int | None = None
    section_title: str | None = None
    subsection_title: str | None = None
    token_count: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class ChunkArtifact(BaseModel):
    document_id: UUID
    user_id: UUID
    chunk_count: int
    created_at: datetime
    chunks: list[ChunkCandidate]

class DocumentIndexingJob(BaseModel):
    job_type: str = "index_document"
    document_id: UUID
    user_id: UUID
    storage_path: str
    attempt: int = 1
    max_attempts: int = 3
