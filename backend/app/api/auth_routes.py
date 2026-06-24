from fastapi import APIRouter, Depends, Request

from app.core.auth import get_current_user
from app.schemas.auth import CurrentUser
from app.services.rate_limit_service import enforce_chat_limits

router = APIRouter(tags=["auth"])

@router.get("/me", response_model=CurrentUser)
async def get_me(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    await enforce_chat_limits(request, current_user)

    return current_user

