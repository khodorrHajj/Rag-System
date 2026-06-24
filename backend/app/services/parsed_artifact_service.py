from datetime import datetime, timezone
import json
from uuid import UUID

from app.config import Settings, get_settings
from app.schemas.ingestion import ParsedDocumentArtifact, ParsedDocumentUnit
from app.services.storage_service import delete_file, download_file, upload_file

def build_parsed_artifact_path(
    user_id: UUID,
    document_id: UUID,
    settings: Settings | None = None,
) -> str:
    current_settings = settings or get_settings()

    return (
        f"{current_settings.parsed_artifact_prefix.rstrip('/')}/"
        f"{user_id}/{document_id}/parsed_document.json"
    )

def save_parsed_artifact(
    *,
    document_id: UUID,
    user_id: UUID,
    file_type: str,
    parser: str,
    units: list[ParsedDocumentUnit],
    settings: Settings | None = None,
) -> str:
    artifact = ParsedDocumentArtifact(
        document_id=document_id,
        user_id=user_id,
        file_type=file_type,
        parser=parser,
        unit_count=len(units),
        created_at=datetime.now(timezone.utc),
        units=units,
    )
    artifact_path = build_parsed_artifact_path(user_id, document_id, settings)
    upload_file(
        artifact_path,
        artifact.model_dump_json(indent=2).encode("utf-8"),
        "application/json",
        settings=settings,
    )

    return artifact_path

def load_parsed_artifact(
    *,
    user_id: UUID,
    document_id: UUID,
    settings: Settings | None = None,
) -> ParsedDocumentArtifact:
    artifact_path = build_parsed_artifact_path(user_id, document_id, settings)
    artifact_bytes = download_file(artifact_path, settings=settings)
    artifact_payload = json.loads(artifact_bytes.decode("utf-8"))

    return ParsedDocumentArtifact.model_validate(artifact_payload)

def delete_parsed_artifact(
    *,
    user_id: UUID,
    document_id: UUID,
    settings: Settings | None = None,
) -> bool:
    artifact_path = build_parsed_artifact_path(user_id, document_id, settings)

    return delete_file(artifact_path, settings=settings)

