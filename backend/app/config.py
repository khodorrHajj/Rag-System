from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    app_name: str = Field(default="RAG Document Assistant API")
    environment: str = Field(default="development")
    api_prefix: str = Field(default="")
    frontend_origin: str = Field(default="http://localhost:4173")
    database_url: str | None = Field(default=None)
    database_host: str = Field(default="localhost")
    database_port: int = Field(default=5432)
    database_name: str = Field(default="rag_document_assistant")
    database_user: str = Field(default="postgres")
    database_password: str = Field(default="postgres")
    database_schema: str = Field(default="public")
    database_ssl_mode: str = Field(default="prefer")
    database_pool_enabled: bool = Field(default=True)
    database_pool_min_size: int = Field(default=1)
    database_pool_max_size: int = Field(default=5)
    database_pool_timeout_seconds: float = Field(default=10.0)
    warm_database_pool_on_startup: bool = Field(default=True)
    embedding_dimension: int = Field(default=384)
    embedding_model_name: str = Field(default="sentence-transformers/all-MiniLM-L6-v2")
    embedding_batch_size: int = Field(default=32)
    embedding_normalize: bool = Field(default=True)
    warm_embedding_model_on_startup: bool = Field(default=True)
    vector_search_weight: float = Field(default=0.7)
    keyword_search_weight: float = Field(default=0.3)
    retrieval_top_k: int = Field(default=8)
    retrieval_candidate_k: int = Field(default=20)
    retrieval_score_threshold: float = Field(default=0.45)
    retrieval_max_query_chars: int = Field(
        default=1000, validation_alias="MAX_RETRIEVAL_QUERY_CHARS"
    )
    retrieval_max_top_k: int = Field(default=10)
    retrieval_max_candidate_k: int = Field(default=50)
    retrieval_preview_chars: int = Field(default=280)
    redis_url: str = Field(default="redis://localhost:6379/0")
    supabase_url: str | None = Field(default=None)
    supabase_publishable_key: str | None = Field(default=None)
    supabase_jwks_url: str | None = Field(default=None)
    supabase_jwt_issuer: str | None = Field(default=None)
    supabase_jwt_audience: str | None = Field(default=None)
    supabase_jwt_secret: str | None = Field(default=None)
    supabase_anon_key: str | None = Field(default=None)
    supabase_secret_key: str | None = Field(default=None)
    supabase_service_role_key: str | None = Field(default=None)
    auth_allow_unverified_jwt: bool = Field(default=False)
    openrouter_api_key: str | None = Field(default=None)
    openrouter_model_primary: str = Field(default="nvidia/nemotron-3-ultra-550b-a55b")
    openrouter_model_fallback: str = Field(default="nex-agi/nex-n2-pro")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1/chat/completions"
    )
    llm_timeout_seconds: int = Field(default=20)
    llm_temperature: float = Field(default=0.2)
    llm_max_tokens: int = Field(default=4000)
    max_context_chars: int = Field(default=16000)
    max_question_chars: int = Field(default=2000)
    max_chat_history_messages: int = Field(default=8)
    storage_bucket_name: str = Field(default="rag-document")
    storage_backend: str = Field(default="local")
    storage_local_root: str = Field(
        default=str(Path(__file__).resolve().parents[2] / "storage" / "private")
    )
    storage_signed_url_secret: str = Field(default="development-storage-signing-secret")
    max_upload_size_mb: int = Field(default=20)
    max_documents_per_user: int = Field(default=5)
    allowed_upload_extensions: tuple[str, ...] = Field(default=("pdf",))
    document_queue_name: str = Field(default="queue:index_documents")
    indexing_max_attempts: int = Field(default=3)
    indexing_queue_block_timeout_seconds: int = Field(default=5)
    indexing_user_lock_ttl_seconds: int = Field(default=1800)
    parsed_artifact_prefix: str = Field(default="artifacts/parsed")
    chunk_artifact_prefix: str = Field(default="artifacts/chunks")
    chunk_max_chars: int = Field(default=1000)
    chunk_overlap_chars: int = Field(default=250)
    chunk_min_chars: int = Field(default=100)
    chunk_hard_max_chars: int = Field(default=1500)
    max_chunks_per_document: int = Field(default=500)
    enable_semantic_chunking: bool = Field(default=True)
    trust_proxy_headers: bool = Field(default=False)
    trusted_proxy_ips: tuple[str, ...] = Field(default=("127.0.0.1", "::1"))
    admin_emails: tuple[str, ...] = Field(default=())
    feedback_comment_max_length: int = Field(default=500)
    observability_recent_limit: int = Field(default=20)
    eval_results_limit: int = Field(default=20)
    eval_answer_preview_chars: int = Field(default=240)
    eval_cases_dir: str = Field(default=str(BACKEND_DIR / "evals"))

    model_config = SettingsConfigDict(
        env_file=(
            str(BACKEND_DIR / ".env"),
            str(REPOSITORY_DIR / ".env"),
        ),
        env_file_encoding="utf-8",
        extra="ignore",
        enable_decoding=False,
    )

    @field_validator("trusted_proxy_ips", mode="before")
    @classmethod
    def parse_trusted_proxy_ips(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ("127.0.0.1", "::1")

        if isinstance(value, str):
            entries = [item.strip() for item in value.split(",") if item.strip()]
            return tuple(entries)

        if isinstance(value, (list, tuple, set)):
            return tuple(str(item).strip() for item in value if str(item).strip())

        raise TypeError(
            "trusted_proxy_ips must be a comma-separated string or list-like value"
        )

    @field_validator("admin_emails", mode="before")
    @classmethod
    def parse_admin_emails(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()

        if isinstance(value, str):
            entries = [
                item.strip().lower() for item in value.split(",") if item.strip()
            ]
            return tuple(entries)

        if isinstance(value, (list, tuple, set)):
            return tuple(
                str(item).strip().lower() for item in value if str(item).strip()
            )

        raise TypeError(
            "admin_emails must be a comma-separated string or list-like value"
        )

    @field_validator("allowed_upload_extensions", mode="before")
    @classmethod
    def parse_allowed_upload_extensions(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ("pdf",)

        if isinstance(value, str):
            entries = [
                item.strip().lower().lstrip(".")
                for item in value.split(",")
                if item.strip()
            ]
            return tuple(entries)

        if isinstance(value, (list, tuple, set)):
            return tuple(
                str(item).strip().lower().lstrip(".")
                for item in value
                if str(item).strip()
            )

        raise TypeError(
            "allowed_upload_extensions must be a comma-separated string or list-like value"
        )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def allowed_cors_origins(self) -> list[str]:
        origins = {self.frontend_origin.rstrip("/")}

        if not self.is_production:
            origins.update(
                {
                    "http://localhost:3000",
                    "http://127.0.0.1:3000",
                    "http://localhost:4173",
                    "http://127.0.0.1:4173",
                    "http://localhost:5173",
                    "http://127.0.0.1:5173",
                }
            )

        return sorted(origin for origin in origins if origin)

    @property
    def resolved_supabase_jwt_issuer(self) -> str | None:
        if self.supabase_jwt_issuer:
            return self.supabase_jwt_issuer.rstrip("/")

        if not self.supabase_url:
            return None

        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def resolved_supabase_jwks_url(self) -> str | None:
        if self.supabase_jwks_url:
            return self.supabase_jwks_url

        if not self.supabase_url:
            return None

        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def resolved_supabase_jwt_audience(self) -> str:
        return self.supabase_jwt_audience or "authenticated"

    @property
    def resolved_supabase_public_key(self) -> str | None:
        return self.supabase_publishable_key or self.supabase_anon_key

    @property
    def resolved_supabase_service_key(self) -> str | None:
        return self.supabase_secret_key or self.supabase_service_role_key

    @property
    def max_upload_size_bytes(self) -> int:
        return max(self.max_upload_size_mb, 1) * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
