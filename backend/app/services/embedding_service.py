from __future__ import annotations

from functools import lru_cache
import logging
from threading import Lock
from time import perf_counter
from typing import Any

from app.config import Settings, get_settings
from app.core.exceptions import AppError, DependencyUnavailableError

logger = logging.getLogger(__name__)
_model_load_lock = Lock()

def _validate_text(text: str, *, field_name: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        raise AppError(f"Cannot generate embeddings for empty {field_name}.", status_code=400)

    return cleaned

@lru_cache(maxsize=4)
def _load_embedding_model(model_name: str):
    with _model_load_lock:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            logger.exception("Sentence Transformers is not installed for embedding model=%s", model_name)
            raise DependencyUnavailableError("Embedding service is temporarily unavailable.") from exc

        logger.info("Loading embedding model name=%s", model_name)
        return SentenceTransformer(model_name)

def get_embedding_model(settings: Settings | None = None):
    current_settings = settings or get_settings()

    return _load_embedding_model(current_settings.embedding_model_name)

def _batched(values: list[str], batch_size: int) -> list[list[str]]:
    effective_batch_size = max(batch_size, 1)
    return [values[index : index + effective_batch_size] for index in range(0, len(values), effective_batch_size)]

def _coerce_embedding_vectors(
    raw_vectors: Any,
    *,
    expected_count: int,
    expected_dimension: int,
) -> list[list[float]]:
    if hasattr(raw_vectors, "tolist"):
        raw_vectors = raw_vectors.tolist()

    if not isinstance(raw_vectors, list):
        raise DependencyUnavailableError("Embedding service returned an unexpected result.")

    vectors: list[list[float]] = []
    for raw_vector in raw_vectors:
        if hasattr(raw_vector, "tolist"):
            raw_vector = raw_vector.tolist()

        if not isinstance(raw_vector, list):
            raise DependencyUnavailableError("Embedding service returned an invalid vector payload.")

        vector = [float(value) for value in raw_vector]
        if len(vector) != expected_dimension:
            raise DependencyUnavailableError(
                "Embedding service returned a vector dimension that does not match configuration."
            )
        vectors.append(vector)

    if len(vectors) != expected_count:
        raise DependencyUnavailableError("Embedding service returned an unexpected number of vectors.")

    return vectors

def embed_texts(texts: list[str], settings: Settings | None = None) -> list[list[float]]:
    current_settings = settings or get_settings()
    if not texts:
        return []

    cleaned_texts = [_validate_text(text, field_name="text") for text in texts]
    model = get_embedding_model(current_settings)
    started_at = perf_counter()
    vectors: list[list[float]] = []

    try:
        for batch in _batched(cleaned_texts, current_settings.embedding_batch_size):
            raw_vectors = model.encode(
                batch,
                batch_size=current_settings.embedding_batch_size,
                convert_to_numpy=True,
                normalize_embeddings=current_settings.embedding_normalize,
                show_progress_bar=False,
            )
            vectors.extend(
                _coerce_embedding_vectors(
                    raw_vectors,
                    expected_count=len(batch),
                    expected_dimension=current_settings.embedding_dimension,
                )
            )
    except AppError:
        raise
    except DependencyUnavailableError:
        raise
    except Exception as exc:
        logger.exception(
            "Embedding batch generation failed model=%s text_count=%s batch_size=%s",
            current_settings.embedding_model_name,
            len(cleaned_texts),
            current_settings.embedding_batch_size,
        )
        raise DependencyUnavailableError("Embedding service is temporarily unavailable.") from exc

    duration_ms = round((perf_counter() - started_at) * 1000)
    logger.info(
        "Generated embeddings model=%s text_count=%s dimension=%s normalize=%s duration_ms=%s",
        current_settings.embedding_model_name,
        len(cleaned_texts),
        current_settings.embedding_dimension,
        current_settings.embedding_normalize,
        duration_ms,
    )

    return vectors

def embed_query(query: str, settings: Settings | None = None) -> list[float]:
    current_settings = settings or get_settings()
    vector = embed_texts([_validate_text(query, field_name="query")], settings=current_settings)

    return vector[0]
