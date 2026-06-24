from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect, status
from starlette.concurrency import run_in_threadpool

from app.core.access import has_developer_access
from app.core.auth import get_current_user, get_current_user_from_websocket
from app.core.chat_realtime import chat_realtime_broker
from app.core.client_ip import get_client_ip
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.schemas.auth import CurrentUser
from app.schemas.chat import (
    ChatMessageListResponse,
    ChatRequest,
    ChatResponse,
    ChatSessionCreateRequest,
    ChatSessionDeleteResponse,
    ChatSessionListResponse,
    ChatSessionSummary,
)
from app.services.chat_service import (
    answer_chat_question,
    create_chat_session,
    delete_chat_session,
    list_chat_messages,
    list_chat_sessions,
)
from app.services.rate_limit_service import enforce_chat_limits

router = APIRouter(prefix="/chat", tags=["chat"])

@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket) -> None:
    try:
        current_user = await get_current_user_from_websocket(websocket)
    except AuthenticationError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await chat_realtime_broker.connect(current_user.user_id, websocket)

    try:
        await websocket.send_json({"type": "chat.connected"})
        while True:
            message = await websocket.receive_text()
            if message.strip().lower() == "ping":
                await websocket.send_json({"type": "chat.pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await chat_realtime_broker.disconnect(current_user.user_id, websocket)

@router.post("/sessions", response_model=ChatSessionSummary)
async def create_session(
    request: Request,
    payload: ChatSessionCreateRequest | None = None,
    current_user: CurrentUser = Depends(get_current_user),
) -> ChatSessionSummary:
    await enforce_chat_limits(request, current_user)
    return await run_in_threadpool(
        create_chat_session,
        user_id=current_user.user_id,
        title=payload.title if payload else None,
        ip_address=get_client_ip(request),
    )

@router.get("/sessions", response_model=ChatSessionListResponse)
async def get_sessions(
    current_user: CurrentUser = Depends(get_current_user),
) -> ChatSessionListResponse:
    sessions = await run_in_threadpool(list_chat_sessions, current_user.user_id)
    return ChatSessionListResponse(sessions=sessions)

@router.get("/sessions/{session_id}/messages", response_model=ChatMessageListResponse)
async def get_session_messages(
    session_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
) -> ChatMessageListResponse:
    messages = await run_in_threadpool(list_chat_messages, session_id, current_user.user_id)
    return ChatMessageListResponse(session_id=session_id, messages=messages)

@router.delete("/sessions/{session_id}", response_model=ChatSessionDeleteResponse)
async def delete_session(
    request: Request,
    session_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
) -> ChatSessionDeleteResponse:
    return await run_in_threadpool(
        delete_chat_session,
        session_id=session_id,
        user_id=current_user.user_id,
        ip_address=get_client_ip(request),
    )

@router.post("", response_model=ChatResponse)
async def chat(
    request: Request,
    payload: ChatRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> ChatResponse:
    await enforce_chat_limits(request, current_user)
    if payload.debug and not has_developer_access(current_user):
        raise AuthorizationError("Debug output is not available for this account.")

    return await run_in_threadpool(
        answer_chat_question,
        user_id=current_user.user_id,
        question=payload.question,
        session_id=payload.session_id,
        document_ids=payload.document_ids,
        debug=payload.debug and has_developer_access(current_user),
        ip_address=get_client_ip(request),
    )
