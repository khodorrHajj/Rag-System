from datetime import datetime, timezone
import json
from uuid import UUID

from app.config import Settings, get_settings
from app.schemas.ingestion import ChunkArtifact, ChunkCandidate
from app.services.storage_service import delete_file, download_file, upload_file

def build_chunk_artifact_path(
    user_id: UUID,
    document_id: UUID,
    settings: Settings | None = None,
) -> str:
    current_settings = settings or get_settings()

    return (
        f"{current_settings.chunk_artifact_prefix.rstrip('/')}/"
        f"{user_id}/{document_id}/chunks.json"
    )

def save_chunk_artifact(
    *,
    document_id: UUID,
    user_id: UUID,
    chunks: list[ChunkCandidate],
    settings: Settings | None = None,
) -> str:
    artifact = ChunkArtifact(
        document_id=document_id,
        user_id=user_id,
        chunk_count=len(chunks),
        created_at=datetime.now(timezone.utc),
        chunks=chunks,
    )
    artifact_path = build_chunk_artifact_path(user_id, document_id, settings)
    upload_file(
        artifact_path,
        artifact.model_dump_json(indent=2).encode("utf-8"),
        "application/json",
        settings=settings,
    )

    return artifact_path

def load_chunk_artifact(
    *,
    user_id: UUID,
    document_id: UUID,
    settings: Settings | None = None,
) -> ChunkArtifact:
    artifact_path = build_chunk_artifact_path(user_id, document_id, settings)
    artifact_bytes = download_file(artifact_path, settings=settings)
    artifact_payload = json.loads(artifact_bytes.decode("utf-8"))

    return ChunkArtifact.model_validate(artifact_payload)

def delete_chunk_artifact(
    *,
    user_id: UUID,
    document_id: UUID,
    settings: Settings | None = None,
) -> bool:
    artifact_path = build_chunk_artifact_path(user_id, document_id, settings)

    return delete_file(artifact_path, settings=settings)
