import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.core.auth import get_current_user
from app.core.client_ip import get_client_ip
from app.core.exceptions import AppError, DependencyUnavailableError, NotFoundError
from app.schemas.auth import CurrentUser
from app.schemas.document import (
    DocumentDeleteResponse,
    DocumentDetail,
    DocumentSummary,
    DocumentUploadResponse,
)
from app.services.audit_log_service import record_audit_log
from app.services.chunk_artifact_service import delete_chunk_artifact
from app.services.document_service import (
    build_storage_path,
    build_document_limit_message,
    count_active_documents_for_user,
    create_document_record,
    get_document_for_user,
    get_owned_document_record,
    list_documents_for_user,
    soft_delete_document,
    update_document_status,
    validate_upload_file,
)
from app.services.job_queue_service import enqueue_document_indexing_job
from app.services.parsed_artifact_service import delete_parsed_artifact
from app.services.rate_limit_service import enforce_upload_limits
from app.services.storage_service import delete_file, upload_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

async def _record_upload_rejection(
    *,
    current_user: CurrentUser,
    request: Request,
    reason: str,
    filename: str | None,
    content_type: str | None,
    status_code: int | None = None,
) -> None:
    metadata = {
        "reason": reason,
        "filename": filename,
        "content_type": content_type,
    }
    if status_code is not None:
        metadata["status_code"] = status_code

    await record_audit_log(
        action="upload_rejected",
        user_id=current_user.user_id,
        resource_type="document",
        metadata=metadata,
        ip_address=get_client_ip(request),
    )

@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
) -> DocumentUploadResponse:
    settings = get_settings()
    await enforce_upload_limits(request, current_user)

    active_document_count = await run_in_threadpool(
        count_active_documents_for_user,
        current_user.user_id,
    )
    if active_document_count >= settings.max_documents_per_user:
        message = build_document_limit_message(settings.max_documents_per_user)
        await _record_upload_rejection(
            current_user=current_user,
            request=request,
            reason=message,
            filename=file.filename,
            content_type=file.content_type,
            status_code=409,
        )
        raise AppError(message, status_code=409)

    try:
        file_bytes = await file.read(settings.max_upload_size_bytes + 1)
        validation = await run_in_threadpool(
            validate_upload_file,
            filename=file.filename,
            content_type=file.content_type,
            file_size_bytes=len(file_bytes),
        )
    except AppError as exc:
        await _record_upload_rejection(
            current_user=current_user,
            request=request,
            reason=exc.detail,
            filename=file.filename,
            content_type=file.content_type,
            status_code=exc.status_code,
        )
        raise
    finally:
        await file.close()

    document_id = uuid4()
    storage_info = build_storage_path(
        current_user.user_id,
        document_id,
        validation["extension"],
    )

    try:
        created_document = await run_in_threadpool(
            create_document_record,
            document_id=document_id,
            user_id=current_user.user_id,
            original_filename=validation["original_filename"],
            safe_filename=storage_info["safe_filename"],
            file_type=validation["extension"],
            storage_path=storage_info["storage_path"],
            file_size_bytes=len(file_bytes),
            status="uploaded",
            error_message=None,
            settings=settings,
        )
    except AppError as exc:
        await _record_upload_rejection(
            current_user=current_user,
            request=request,
            reason=exc.detail,
            filename=file.filename,
            content_type=file.content_type,
            status_code=exc.status_code,
        )
        raise

    try:
        await run_in_threadpool(
            upload_file,
            storage_info["storage_path"],
            file_bytes,
            validation["content_type"],
        )
    except DependencyUnavailableError as exc:
        logger.exception(
            "Private storage upload failed for document_id=%s user_id=%s",
            document_id,
            current_user.user_id,
        )
        await run_in_threadpool(
            update_document_status,
            document_id=document_id,
            user_id=current_user.user_id,
            status="failed",
            error_message="Storage upload failed.",
        )
        await _record_upload_rejection(
            current_user=current_user,
            request=request,
            reason="Storage upload failed.",
            filename=file.filename,
            content_type=file.content_type,
            status_code=exc.status_code,
        )
        raise AppError(
            "File upload is temporarily unavailable. Please try again later.",
            status_code=503,
        ) from exc

    await record_audit_log(
        action="document_uploaded",
        user_id=current_user.user_id,
        resource_type="document",
        resource_id=document_id,
        metadata={
            "original_filename": validation["original_filename"],
            "file_type": validation["extension"],
            "file_size_bytes": len(file_bytes),
            "storage_path": storage_info["storage_path"],
        },
        ip_address=get_client_ip(request),
    )

    try:
        await enqueue_document_indexing_job(
            document_id=document_id,
            user_id=current_user.user_id,
            storage_path=storage_info["storage_path"],
        )
    except DependencyUnavailableError as exc:
        logger.exception(
            "Indexing queue enqueue failed for document_id=%s user_id=%s",
            document_id,
            current_user.user_id,
        )
        await run_in_threadpool(
            update_document_status,
            document_id=document_id,
            user_id=current_user.user_id,
            status="uploaded",
            error_message="Indexing queue unavailable.",
        )
        await _record_upload_rejection(
            current_user=current_user,
            request=request,
            reason="Indexing queue unavailable.",
            filename=file.filename,
            content_type=file.content_type,
            status_code=exc.status_code,
        )
        raise AppError(
            "Document was uploaded but could not be queued for processing. Please try again later.",
            status_code=503,
        ) from exc

    queued_document = await run_in_threadpool(
        update_document_status,
        document_id=document_id,
        user_id=current_user.user_id,
        status="queued",
        error_message=None,
    )

    await record_audit_log(
        action="indexing_job_enqueued",
        user_id=current_user.user_id,
        resource_type="document",
        resource_id=document_id,
        metadata={
            "queue_name": settings.document_queue_name,
            "storage_path": storage_info["storage_path"],
        },
        ip_address=get_client_ip(request),
    )

    document_status = queued_document["status"] if queued_document else created_document["status"]

    return DocumentUploadResponse(
        document_id=document_id,
        status=document_status,
    )

@router.get("", response_model=list[DocumentSummary])
async def list_documents(
    current_user: CurrentUser = Depends(get_current_user),
) -> list[DocumentSummary]:
    documents = await run_in_threadpool(
        list_documents_for_user,
        current_user.user_id,
        include_deleted=False,
    )

    return [DocumentSummary.model_validate(document) for document in documents]

@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
) -> DocumentDetail:
    document = await run_in_threadpool(
        get_document_for_user,
        document_id,
        current_user.user_id,
    )
    if document is None:
        raise NotFoundError("Document not found.")

    return DocumentDetail.model_validate(document)

@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(
    document_id: UUID,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
) -> DocumentDeleteResponse:
    existing_document = await run_in_threadpool(
        get_owned_document_record,
        document_id,
        current_user.user_id,
    )
    if existing_document is None:
        raise NotFoundError("Document not found.")

    deleted_document = await run_in_threadpool(
        soft_delete_document,
        document_id,
        current_user.user_id,
    )
    if deleted_document is None:
        raise NotFoundError("Document not found.")

    try:
        await run_in_threadpool(delete_file, existing_document["storage_path"])
    except DependencyUnavailableError:
        logger.warning(
            "Storage cleanup failed after soft-delete for document_id=%s user_id=%s",
            document_id,
            current_user.user_id,
            exc_info=True,
        )

    try:
        await run_in_threadpool(
            delete_parsed_artifact,
            user_id=current_user.user_id,
            document_id=document_id,
        )
    except DependencyUnavailableError:
        logger.warning(
            "Parsed artifact cleanup failed after soft-delete for document_id=%s user_id=%s",
            document_id,
            current_user.user_id,
            exc_info=True,
        )

    try:
        await run_in_threadpool(
            delete_chunk_artifact,
            user_id=current_user.user_id,
            document_id=document_id,
        )
    except DependencyUnavailableError:
        logger.warning(
            "Chunk artifact cleanup failed after soft-delete for document_id=%s user_id=%s",
            document_id,
            current_user.user_id,
            exc_info=True,
        )

    await record_audit_log(
        action="document_deleted",
        user_id=current_user.user_id,
        resource_type="document",
        resource_id=document_id,
        metadata={
            "storage_path": existing_document["storage_path"],
        },
        ip_address=get_client_ip(request),
    )

    return DocumentDeleteResponse(
        document_id=document_id,
        status=deleted_document["status"],
    )
