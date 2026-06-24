from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, field_validator

class FeedbackCreateRequest(BaseModel):
    message_id: UUID
    rating: Literal["positive", "negative"]
    comment: str | None = None

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()
        return cleaned or None

class FeedbackRecord(BaseModel):
    feedback_id: UUID
    user_id: UUID
    message_id: UUID
    rating: Literal["positive", "negative"]
    comment: str | None = None
    created_at: datetime
    user_email: str | None = None

class FeedbackListResponse(BaseModel):
    feedback: list[FeedbackRecord]
