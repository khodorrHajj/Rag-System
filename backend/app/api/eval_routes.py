from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.core.access import require_developer_access
from app.schemas.auth import CurrentUser
from app.schemas.evaluation import EvaluationResultsListResponse, EvaluationRunRequest, EvaluationRunResponse
from app.services.evaluation_service import list_evaluation_runs, run_evaluations

router = APIRouter(prefix="/eval", tags=["evaluation"])

@router.post("/run", response_model=EvaluationRunResponse)
async def run_eval(
    payload: EvaluationRunRequest,
    current_user: CurrentUser = Depends(require_developer_access),
) -> EvaluationRunResponse:
    return await run_in_threadpool(
        run_evaluations,
        user_id=current_user.user_id,
        run_all=payload.run_all,
        case_name=payload.case_name,
        case=payload.case,
    )

@router.get("/results", response_model=EvaluationResultsListResponse)
async def get_eval_results(
    current_user: CurrentUser = Depends(require_developer_access),
) -> EvaluationResultsListResponse:
    runs = await run_in_threadpool(list_evaluation_runs)
    return EvaluationResultsListResponse(runs=runs)
