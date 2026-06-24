from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.core.access import require_developer_access
from app.schemas.admin import DeveloperDashboardResponse
from app.schemas.auth import CurrentUser
from app.services.observability_service import get_developer_dashboard

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/dashboard", response_model=DeveloperDashboardResponse)
async def developer_dashboard(
    current_user: CurrentUser = Depends(require_developer_access),
) -> DeveloperDashboardResponse:
    return await run_in_threadpool(get_developer_dashboard)
