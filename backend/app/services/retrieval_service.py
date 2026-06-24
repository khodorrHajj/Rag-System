from __future__ import annotations

from collections.abc import Iterable
from time import perf_counter
from typing import Any
from uuid import UUID
import re

import logging
import psycopg
from pgvector import Vector
from psycopg.types.json import Jsonb

from app.config import Settings, get_settings
from app.core.database import database_connection
from app.core.exceptions import AppError, DependencyUnavailableError
from app.schemas.retrieval import RetrievalDebugInfo, RetrievalResult, RetrievedChunk
from app.services.embedding_service import embed_query
from app.services.reranking_service import rerank_chunks

logger = logging.getLogger(__name__)

SECTION_REFERENCE_RE = re.compile(
    r"(?i)(?:according to\s+)?the\s+['\"]?(.+?)['\"]?\s+(?:section|chapter|part)\b"
)


def _extract_section_reference(query: str) -> str | None:
    match = SECTION_REFERENCE_RE.search(query)
    if match:
        section = match.group(1).strip().strip("'\"")
        if section and len(section) >= 3:
            return section
    return None


KEYWORD_TSVECTOR_SQL = """
(
  setweight(to_tsvector('english', coalesce(dc.content, '')), 'A') ||
  setweight(to_tsvector('english', coalesce(dc.section_title, '')), 'B') ||
  setweight(to_tsvector('english', coalesce(dc.subsection_title, '')), 'B')
)
"""

ANALYTICAL_QUERY_TERMS = {
    "which",
    "greatest",
    "highest",
    "lowest",
    "largest",
    "smallest",
    "compare",
    "comparison",
    "between",
    "before",
    "after",
    "same",
}
ANALYTICAL_SPLIT_RE = re.compile(
    r"(?i)\bfor\s+(?:that|the same)\s+region\b[:,]?\s*|\?\s+|;\s+"
)
KEYWORD_QUERY_STOPWORDS = {
    "a",
    "about",
    "according",
    "all",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "before",
    "between",
    "by",
    "did",
    "do",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "much",
    "of",
    "on",
    "or",
    "same",
    "say",
    "that",
    "the",
    "their",
    "there",
    "these",
    "this",
    "to",
    "was",
    "what",
    "which",
    "with",
}


def _run_db_operation(operation_name: str, callback):
    try:
        return callback()
    except AppError:
        raise
    except psycopg.Error as exc:
        logger.exception("Database operation failed during %s", operation_name)
        raise DependencyUnavailableError(
            "Database service is temporarily unavailable."
        ) from exc


def _coerce_user_id(user_id: str | UUID) -> UUID:
    if isinstance(user_id, UUID):
        return user_id

    try:
        return UUID(str(user_id))
    except ValueError as exc:
        raise AppError(
            "Invalid user identifier for retrieval.", status_code=400
        ) from exc


def _normalize_document_ids(document_ids: Iterable[str | UUID] | None) -> list[UUID]:
    if not document_ids:
        return []

    normalized: list[UUID] = []
    seen: set[UUID] = set()
    for document_id in document_ids:
        try:
            candidate = (
                document_id if isinstance(document_id, UUID) else UUID(str(document_id))
            )
        except ValueError as exc:
            raise AppError(
                "One or more document IDs were invalid.", status_code=400
            ) from exc
        if candidate not in seen:
            normalized.append(candidate)
            seen.add(candidate)

    return normalized


def _clean_query(query: str, settings: Settings) -> str:
    cleaned = query.strip()
    if not cleaned:
        raise AppError("Query must not be empty.", status_code=400)
    if len(cleaned) > settings.retrieval_max_query_chars:
        raise AppError(
            f"Query exceeds the maximum allowed length of {settings.retrieval_max_query_chars} characters.",
            status_code=400,
        )

    return cleaned


def _resolve_top_k(value: int | None, settings: Settings) -> int:
    requested = value or settings.retrieval_top_k
    return max(1, min(requested, settings.retrieval_max_top_k))


def _resolve_candidate_k(value: int | None, top_k: int, settings: Settings) -> int:
    requested = value or settings.retrieval_candidate_k
    requested = max(requested, top_k)
    return max(top_k, min(requested, settings.retrieval_max_candidate_k))


def _is_analytical_query(query: str) -> bool:
    lowered = query.lower()
    term_hits = sum(1 for term in ANALYTICAL_QUERY_TERMS if term in lowered)
    return (
        term_hits >= 2
        or lowered.count("?") > 1
        or lowered.count(",") >= 2
        or " and " in lowered
    )


def _derive_query_variants(query: str) -> list[str]:
    normalized_query = " ".join(query.strip().split())
    if not normalized_query:
        return []

    variants: list[str] = [normalized_query]
    seen = {normalized_query.lower()}

    def add_variant(value: str) -> None:
        cleaned = " ".join(value.strip(" ,.;:").split())
        if len(cleaned) < 24:
            return
        lowered = cleaned.lower()
        if lowered in seen:
            return
        seen.add(lowered)
        variants.append(cleaned)

    for segment in ANALYTICAL_SPLIT_RE.split(normalized_query):
        add_variant(segment)

    if len(normalized_query) >= 90:
        for segment in re.split(r",\s+", normalized_query):
            add_variant(segment)

    if " and " in normalized_query.lower():
        for segment in re.split(r"(?i)\s+\band\b\s+", normalized_query):
            add_variant(segment)

    return variants[:4]


def _build_keyword_queries(
    query_variants: list[str],
    *,
    section_reference: str | None = None,
) -> list[str]:
    keyword_queries: list[str] = []
    seen: set[str] = set()

    def add_query(value: str) -> None:
        cleaned = " ".join(value.strip(" ,.;:").split())
        if len(cleaned) < 8:
            return
        lowered = cleaned.lower()
        if lowered in seen:
            return
        seen.add(lowered)
        keyword_queries.append(cleaned)

    for variant in query_variants:
        add_query(variant)

        tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", variant.lower())
            if token not in KEYWORD_QUERY_STOPWORDS
        ]
        if tokens:
            add_query(" ".join(tokens[:10]))

    if section_reference:
        add_query(section_reference)

    return keyword_queries[:10]


def _build_access_filters(
    *,
    user_id: UUID,
    document_ids: list[UUID],
) -> tuple[list[str], list[Any]]:
    filters = [
        "d.deleted_at IS NULL",
        "d.status = 'indexed'",
        """
        (
          d.user_id = %s
          OR EXISTS (
            SELECT 1
            FROM public.document_permissions AS dp
            WHERE dp.document_id = d.id
              AND dp.permitted_user_id = %s
              AND dp.permission_level = 'read'
          )
        )
        """,
    ]
    params: list[Any] = [user_id, user_id]

    if document_ids:
        filters.append("d.id = ANY(%s)")
        params.append(document_ids)

    return filters, params


def _build_chunk_from_row(row: dict[str, Any]) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        user_id=row["user_id"],
        source_file=row["source_file"],
        chunk_index=row["chunk_index"],
        content=row["content"],
        page_number=row["page_number"],
        section_title=row["section_title"],
        subsection_title=row["subsection_title"],
        token_count=row["token_count"],
        metadata=row["metadata"] or {},
        vector_score=None,
        keyword_score=None,
        combined_score=0.0,
    )


def _vector_similarity(distance: float | int | None) -> float:
    if distance is None:
        return 0.0

    similarity = 1.0 - float(distance)
    return max(0.0, min(similarity, 1.0))


def _normalize_score_map(score_map: dict[UUID, float]) -> dict[UUID, float]:
    if not score_map:
        return {}

    minimum = min(score_map.values())
    maximum = max(score_map.values())
    if maximum - minimum < 1e-9:
        return {
            chunk_id: 1.0 if score > 0 else 0.0 for chunk_id, score in score_map.items()
        }

    return {
        chunk_id: (score - minimum) / (maximum - minimum)
        for chunk_id, score in score_map.items()
    }


def _execute_vector_search(
    *,
    user_id: UUID,
    query_embedding: list[float],
    document_ids: list[UUID],
    candidate_k: int,
    settings: Settings,
) -> list[dict[str, Any]]:
    filters, params = _build_access_filters(user_id=user_id, document_ids=document_ids)
    where_clause = " AND ".join(filters)
    query_vector = Vector(query_embedding)

    def callback() -> list[dict[str, Any]]:
        with database_connection(settings) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        dc.id AS chunk_id,
                        dc.document_id,
                        dc.user_id,
                        d.original_filename AS source_file,
                        dc.chunk_index,
                        dc.content,
                        dc.page_number,
                        dc.section_title,
                        dc.subsection_title,
                        dc.token_count,
                        dc.metadata,
                        (dc.embedding <=> %s::vector) AS vector_distance
                    FROM public.document_chunks AS dc
                    JOIN public.documents AS d
                      ON d.id = dc.document_id
                    WHERE {where_clause}
                    ORDER BY dc.embedding <=> %s::vector ASC
                    LIMIT %s
                    """,
                    [query_vector, *params, query_vector, candidate_k],
                )
                return cursor.fetchall()

    return _run_db_operation("vector_retrieval_search", callback)


def _execute_keyword_search(
    *,
    user_id: UUID,
    query: str,
    document_ids: list[UUID],
    candidate_k: int,
    settings: Settings,
) -> list[dict[str, Any]]:
    filters, params = _build_access_filters(user_id=user_id, document_ids=document_ids)
    where_clause = " AND ".join(filters)
    phrase_pattern = f"%{query}%"

    def callback() -> list[dict[str, Any]]:
        with database_connection(settings) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        dc.id AS chunk_id,
                        dc.document_id,
                        dc.user_id,
                        d.original_filename AS source_file,
                        dc.chunk_index,
                        dc.content,
                        dc.page_number,
                        dc.section_title,
                        dc.subsection_title,
                        dc.token_count,
                        dc.metadata,
                        ts_rank_cd(
                          {KEYWORD_TSVECTOR_SQL},
                          websearch_to_tsquery('english', %s)
                        ) AS keyword_rank
                    FROM public.document_chunks AS dc
                    JOIN public.documents AS d
                      ON d.id = dc.document_id
                    WHERE {where_clause}
                      AND (
                        {KEYWORD_TSVECTOR_SQL} @@ websearch_to_tsquery('english', %s)
                        OR dc.content ILIKE %s
                        OR coalesce(dc.section_title, '') ILIKE %s
                        OR coalesce(dc.subsection_title, '') ILIKE %s
                        OR d.original_filename ILIKE %s
                      )
                    ORDER BY keyword_rank DESC, dc.chunk_index ASC
                    LIMIT %s
                    """,
                    [
                        query,
                        *params,
                        query,
                        phrase_pattern,
                        phrase_pattern,
                        phrase_pattern,
                        phrase_pattern,
                        candidate_k,
                    ],
                )
                return cursor.fetchall()

    return _run_db_operation("keyword_retrieval_search", callback)


def _merge_candidates(
    *,
    vector_rows: list[dict[str, Any]],
    keyword_rows: list[dict[str, Any]],
    settings: Settings,
) -> list[RetrievedChunk]:
    merged: dict[UUID, RetrievedChunk] = {}
    vector_scores_raw: dict[UUID, float] = {}
    keyword_scores_raw: dict[UUID, float] = {}

    for row in vector_rows:
        chunk = merged.get(row["chunk_id"]) or _build_chunk_from_row(row)
        merged[row["chunk_id"]] = chunk
        vector_scores_raw[row["chunk_id"]] = _vector_similarity(
            row.get("vector_distance")
        )

    for row in keyword_rows:
        chunk = merged.get(row["chunk_id"]) or _build_chunk_from_row(row)
        merged[row["chunk_id"]] = chunk
        keyword_scores_raw[row["chunk_id"]] = max(
            float(row.get("keyword_rank") or 0.0), 0.0
        )

    normalized_vector_scores = _normalize_score_map(vector_scores_raw)
    normalized_keyword_scores = _normalize_score_map(keyword_scores_raw)

    merged_candidates: list[RetrievedChunk] = []
    for chunk_id, candidate in merged.items():
        vector_score = normalized_vector_scores.get(chunk_id)
        keyword_score = normalized_keyword_scores.get(chunk_id)
        combined_score = settings.vector_search_weight * (
            vector_score or 0.0
        ) + settings.keyword_search_weight * (keyword_score or 0.0)
        merged_candidates.append(
            candidate.model_copy(
                update={
                    "vector_score": round(vector_score, 6)
                    if vector_score is not None
                    else None,
                    "keyword_score": round(keyword_score, 6)
                    if keyword_score is not None
                    else None,
                    "combined_score": round(min(combined_score, 1.0), 6),
                }
            )
        )

    merged_candidates.sort(
        key=lambda chunk: (
            chunk.combined_score,
            chunk.vector_score or 0.0,
            chunk.keyword_score or 0.0,
        ),
        reverse=True,
    )

    return merged_candidates


def _attach_companion_chunks(
    chunks: list[RetrievedChunk],
    *,
    document_ids: list[UUID],
    page_numbers: list[int],
    exclude_chunk_ids: list[UUID],
    base_score: float,
    settings: Settings,
) -> None:
    if not page_numbers or not document_ids:
        return
    params: list[Any] = [document_ids, page_numbers]
    placeholders = (
        ", ".join(f"${i}" for i in range(3, 3 + len(exclude_chunk_ids)))
        if exclude_chunk_ids
        else ""
    )
    exclude_clause = f" AND dc.id NOT IN ({placeholders})" if placeholders else ""
    params.extend(exclude_chunk_ids)
    sql = f"""
        SELECT
            dc.id AS chunk_id,
            dc.document_id,
            dc.user_id,
            d.original_filename AS source_file,
            dc.chunk_index,
            dc.content,
            dc.page_number,
            dc.section_title,
            dc.subsection_title,
            dc.token_count,
            dc.metadata
        FROM public.document_chunks AS dc
        JOIN public.documents AS d
          ON d.id = dc.document_id
        WHERE dc.document_id = ANY(%s)
          AND dc.page_number = ANY(%s)
          {exclude_clause}
        ORDER BY dc.chunk_index
    """

    def callback() -> list[dict[str, Any]]:
        with database_connection(settings) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchall()

    rows = _run_db_operation("companion_chunk_retrieval", callback)
    if not rows:
        return
    penalty = 0.0
    existing_ids = {c.chunk_id for c in chunks}
    for row in rows:
        chunk_id = row["chunk_id"]
        if chunk_id in existing_ids:
            continue
        existing_ids.add(chunk_id)
        companion = _build_chunk_from_row(row)
        companion.combined_score = max(base_score - penalty, 0.0)
        chunks.append(companion)
        penalty += 0.001


def _record_retrieval_log(
    *,
    user_id: UUID,
    query: str,
    original_question: str | None,
    top_k: int,
    threshold: float | None,
    chunks: list[RetrievedChunk],
    latency_ms: int,
    session_id: UUID | None,
    message_id: UUID | None,
    settings: Settings,
) -> None:
    retrieved_chunk_ids = [str(chunk.chunk_id) for chunk in chunks]
    scores = [
        {
            "chunk_id": str(chunk.chunk_id),
            "combined_score": chunk.combined_score,
            "vector_score": chunk.vector_score,
            "keyword_score": chunk.keyword_score,
        }
        for chunk in chunks
    ]

    def callback() -> None:
        with database_connection(settings) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO public.retrieval_logs (
                        user_id,
                        session_id,
                        message_id,
                        query,
                        original_question,
                        top_k,
                        threshold,
                        retrieved_chunk_ids,
                        scores,
                        model_used,
                        latency_ms
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        session_id,
                        message_id,
                        query,
                        original_question,
                        top_k,
                        threshold,
                        Jsonb(retrieved_chunk_ids),
                        Jsonb(scores),
                        settings.embedding_model_name,
                        latency_ms,
                    ),
                )
            connection.commit()

    _run_db_operation("record_retrieval_log", callback)


def retrieve_relevant_chunks(
    user_id: str | UUID,
    query: str,
    document_ids: list[str | UUID] | None,
    top_k: int | None,
    candidate_k: int | None,
    threshold: float | None,
    session_id: UUID | None = None,
    message_id: UUID | None = None,
    original_question: str | None = None,
    settings: Settings | None = None,
    record_log: bool = True,
) -> RetrievalResult:
    current_settings = settings or get_settings()
    resolved_user_id = _coerce_user_id(user_id)
    cleaned_query = _clean_query(query, current_settings)
    section_ref = _extract_section_reference(cleaned_query) or (
        _extract_section_reference(original_question) if original_question else None
    )
    normalized_document_ids = _normalize_document_ids(document_ids)
    resolved_top_k = _resolve_top_k(top_k, current_settings)
    resolved_candidate_k = _resolve_candidate_k(
        candidate_k, resolved_top_k, current_settings
    )
    resolved_threshold = (
        threshold
        if threshold is not None
        else current_settings.retrieval_score_threshold
    )
    query_variants = [cleaned_query]
    if _is_analytical_query(cleaned_query):
        query_variants = _derive_query_variants(cleaned_query)
        resolved_top_k = min(
            max(resolved_top_k, 8), current_settings.retrieval_max_top_k
        )
        resolved_candidate_k = min(
            max(resolved_candidate_k, max(resolved_top_k * 5, 40)),
            current_settings.retrieval_max_candidate_k,
        )
        if threshold is None and resolved_threshold is not None:
            resolved_threshold = max(0.28, resolved_threshold - 0.08)
    started_at = perf_counter()

    query_embedding = embed_query(cleaned_query, settings=current_settings)
    if len(query_embedding) != current_settings.embedding_dimension:
        raise AppError(
            "Query embedding dimension did not match the configured retrieval dimension.",
            status_code=500,
        )

    vector_rows = _execute_vector_search(
        user_id=resolved_user_id,
        query_embedding=query_embedding,
        document_ids=normalized_document_ids,
        candidate_k=resolved_candidate_k,
        settings=current_settings,
    )
    keyword_rows: list[dict[str, Any]] = []
    keyword_queries = _build_keyword_queries(
        query_variants,
        section_reference=section_ref,
    )
    if keyword_queries:
        keyword_candidate_k = min(
            resolved_candidate_k,
            max(resolved_top_k * 2, resolved_top_k + 4),
        )
        for keyword_query in keyword_queries:
            keyword_rows.extend(
                _execute_keyword_search(
                    user_id=resolved_user_id,
                    query=keyword_query,
                    document_ids=normalized_document_ids,
                    candidate_k=keyword_candidate_k,
                    settings=current_settings,
                )
            )

    merged_candidates = _merge_candidates(
        vector_rows=vector_rows,
        keyword_rows=keyword_rows,
        settings=current_settings,
    )
    reranked_chunks = rerank_chunks(
        cleaned_query,
        merged_candidates,
        resolved_top_k,
        section_reference=section_ref,
    )

    if section_ref and reranked_chunks and normalized_document_ids:
        companion_pages: set[int] = set()
        for chunk in reranked_chunks:
            if chunk.page_number is not None:
                companion_pages.add(chunk.page_number)
        if companion_pages:
            min_score = min(c.combined_score for c in reranked_chunks) - 0.001
            companion_ids = [c.chunk_id for c in reranked_chunks]
            _attach_companion_chunks(
                reranked_chunks,
                document_ids=normalized_document_ids,
                page_numbers=list(companion_pages),
                exclude_chunk_ids=companion_ids,
                base_score=min_score,
                settings=current_settings,
            )

    latency_ms = round((perf_counter() - started_at) * 1000)
    retrieval_passed = bool(reranked_chunks) and (
        resolved_threshold is None
        or reranked_chunks[0].combined_score >= resolved_threshold
    )

    debug = RetrievalDebugInfo(
        candidate_count=len(merged_candidates),
        vector_candidate_count=len(vector_rows),
        keyword_candidate_count=len(keyword_rows),
        top_k=resolved_top_k,
        candidate_k=resolved_candidate_k,
        threshold=resolved_threshold,
        latency_ms=latency_ms,
        vector_weight=current_settings.vector_search_weight,
        keyword_weight=current_settings.keyword_search_weight,
        document_filter_count=len(normalized_document_ids),
    )

    if record_log:
        _record_retrieval_log(
            user_id=resolved_user_id,
            query=cleaned_query,
            original_question=original_question,
            top_k=resolved_top_k,
            threshold=resolved_threshold,
            chunks=reranked_chunks,
            latency_ms=latency_ms,
            session_id=session_id,
            message_id=message_id,
            settings=current_settings,
        )
    logger.info(
        "Retrieved chunks user_id=%s top_k=%s candidate_k=%s candidate_count=%s passed=%s latency_ms=%s",
        resolved_user_id,
        resolved_top_k,
        resolved_candidate_k,
        len(merged_candidates),
        retrieval_passed,
        latency_ms,
    )

    return RetrievalResult(
        retrieval_passed=retrieval_passed,
        chunks=reranked_chunks,
        debug=debug,
    )
