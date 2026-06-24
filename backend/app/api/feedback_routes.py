from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool

from app.core.access import has_developer_access
from app.core.auth import get_current_user
from app.core.client_ip import get_client_ip
from app.schemas.auth import CurrentUser
from app.schemas.feedback import FeedbackCreateRequest, FeedbackListResponse, FeedbackRecord
from app.services.audit_log_service import record_audit_log
from app.services.feedback_service import list_feedback, submit_feedback

router = APIRouter(prefix="/feedback", tags=["feedback"])

@router.post("", response_model=FeedbackRecord)
async def create_feedback(
    request: Request,
    payload: FeedbackCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> FeedbackRecord:
    allow_cross_user = has_developer_access(current_user)
    feedback = await run_in_threadpool(
        submit_feedback,
        current_user_id=current_user.user_id,
        message_id=payload.message_id,
        rating=payload.rating,
        comment=payload.comment,
        allow_cross_user=allow_cross_user,
    )
    await record_audit_log(
        action="feedback_submitted",
        user_id=current_user.user_id,
        resource_type="chat_message",
        resource_id=payload.message_id,
        metadata={"rating": payload.rating, "has_comment": bool(payload.comment)},
        ip_address=get_client_ip(request),
    )
    return feedback

@router.get("", response_model=FeedbackListResponse)
async def get_feedback(
    all_feedback: bool = Query(default=False, alias="all"),
    current_user: CurrentUser = Depends(get_current_user),
) -> FeedbackListResponse:
    include_all = all_feedback and has_developer_access(current_user)
    feedback = await run_in_threadpool(
        list_feedback,
        current_user_id=current_user.user_id,
        include_all=include_all,
    )
    return FeedbackListResponse(feedback=feedback)
