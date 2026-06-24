from uuid import UUID

from pydantic import BaseModel

class CurrentUser(BaseModel):
    user_id: UUID
    email: str | None = None
    role: str | None = None
    is_admin: bool = False
    can_access_developer_tools: bool = False
