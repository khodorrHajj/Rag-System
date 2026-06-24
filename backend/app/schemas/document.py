from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

class DocumentUploadResponse(BaseModel):
    document_id: UUID
    status: str

class DocumentSummary(BaseModel):
    document_id: UUID
    original_filename: str
    safe_filename: str
    file_type: str
    file_size_bytes: int
    status: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

class DocumentDetail(DocumentSummary):
    deleted_at: datetime | None = None

class DocumentDeleteResponse(BaseModel):
    document_id: UUID
    status: str
