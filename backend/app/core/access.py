from app.config import Settings, get_settings
from app.core.auth import get_current_user
from app.core.exceptions import AuthorizationError
from app.schemas.auth import CurrentUser
from fastapi import Depends

def has_developer_access(
    current_user: CurrentUser,
    settings: Settings | None = None,
) -> bool:
    if current_user.can_access_developer_tools:
        return True

    current_settings = settings or get_settings()
    user_email = (current_user.email or "").strip().lower()
    if not user_email:
        return False

    return user_email in current_settings.admin_emails

def require_developer_access(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if not has_developer_access(current_user):
        raise AuthorizationError("Developer monitoring is not available for this account.")

    return current_user
