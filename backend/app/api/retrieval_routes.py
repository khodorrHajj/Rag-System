from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.core.auth import get_current_user
from app.schemas.auth import CurrentUser
from app.schemas.retrieval import (
    RetrievalTestChunkResponse,
    RetrievalTestRequest,
    RetrievalTestResponse,
)
from app.services.rate_limit_service import enforce_retrieval_limits
from app.services.retrieval_service import retrieve_relevant_chunks

router = APIRouter(prefix="/retrieval", tags=["retrieval"])

def _build_preview(content: str, preview_chars: int) -> str:
    cleaned = content.strip()
    if len(cleaned) <= preview_chars:
        return cleaned

    return f"{cleaned[:preview_chars].rstrip()}..."

@router.post("/test", response_model=RetrievalTestResponse)
async def retrieval_test(
    request: Request,
    payload: RetrievalTestRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> RetrievalTestResponse:
    settings = get_settings()
    await enforce_retrieval_limits(request, current_user)
    result = await run_in_threadpool(
        retrieve_relevant_chunks,
        current_user.user_id,
        payload.query,
        payload.document_ids,
        payload.top_k,
        payload.candidate_k,
        payload.threshold,
    )

    return RetrievalTestResponse(
        retrieval_passed=result.retrieval_passed,
        chunks=[
            RetrievalTestChunkResponse(
                chunk_id=chunk.chunk_id,
                content_preview=_build_preview(chunk.content, settings.retrieval_preview_chars),
                document_id=chunk.document_id,
                source_file=chunk.source_file,
                page_number=chunk.page_number,
                section_title=chunk.section_title,
                subsection_title=chunk.subsection_title,
                chunk_index=chunk.chunk_index,
                combined_score=chunk.combined_score,
                vector_score=chunk.vector_score,
                keyword_score=chunk.keyword_score,
            )
            for chunk in result.chunks
        ],
        debug=result.debug,
    )
