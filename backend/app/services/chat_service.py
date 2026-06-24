from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any
from uuid import UUID, uuid4

import psycopg

from app.config import Settings, get_settings
from app.core.chat_realtime import chat_realtime_broker
from app.core.database import database_connection
from app.core.exceptions import AppError, DependencyUnavailableError, NotFoundError
from app.schemas.chat import (
    ChatDebugChunk,
    ChatDebugInfo,
    ChatMessageCitation,
    ChatMessageRecord,
    ChatResponse,
    ChatSessionDeleteResponse,
    ChatSessionSummary,
)
from app.schemas.retrieval import RetrievalDebugInfo, RetrievalResult, RetrievedChunk
from app.services.audit_log_service import record_audit_log_sync
from app.services.llm_service import generate_chat_completion
from app.services.prompt_builder import (
    _derive_prompt_subqueries,
    _format_context_block,
    build_grounded_prompt,
    build_retrieval_query,
)
from app.services.retrieval_service import retrieve_relevant_chunks

logger = logging.getLogger(__name__)

NOT_ENOUGH_INFO_MESSAGE = "I do not have enough information in the uploaded documents to answer that question."
EXTRACTIVE_FALLBACK_MODEL_NAME = "extractive-fallback"
SOURCE_BRACKET_PATTERN = re.compile(r"\[(?:Source|Sources)\s+([^\]]+)\]", re.IGNORECASE)
ANSWER_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")
ANSWER_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
REGION_CONTEXT_REFERENCE_PATTERN = re.compile(
    r"\b(?:that|those|these|both|same)\s+region(?:s)?\b|\bthere\b",
    re.IGNORECASE,
)
NOT_ENOUGH_INFO_PATTERNS = (
    re.compile(r"\bi do not have enough information\b"),
    re.compile(r"\bnot enough information\b"),
    re.compile(r"\bdo not provide enough information\b"),
    re.compile(r"\binsufficient information\b"),
    re.compile(r"\bdoes not provide specific information\b"),
    re.compile(r"\bremains uncertain based on the provided context\b"),
)
REGION_REFERENCE_PATTERN = re.compile(
    r"(?i)\b(?:for\s+)?(?:that(?:\s+same)?|the same)\s+region\b"
)
LOCATION_REFERENCE_PATTERN = re.compile(r"(?i)\bthere\b")


@dataclass(frozen=True)
class FinalizedCitationSource:
    source_number: int
    chunk: RetrievedChunk


def _message_citations_supports_source_number() -> bool:
    def callback() -> bool:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'message_citations'
                      AND column_name = 'source_number'
                    LIMIT 1
                    """
                )
                return cursor.fetchone() is not None

    return _run_db_operation("check_message_citations_source_number_support", callback)


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


def _update_chat_message_content(
    *,
    message_id: UUID,
    content: str,
    settings: Settings,
) -> None:
    def callback() -> None:
        with database_connection(settings) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE public.chat_messages
                    SET content = %s
                    WHERE id = %s
                    """,
                    (content, message_id),
                )
            connection.commit()

    _run_db_operation("update_chat_message_content", callback)


def _clean_title(title: str | None) -> str | None:
    if title is None:
        return None

    cleaned = title.strip()
    return cleaned or None


def _default_session_title(question: str) -> str:
    cleaned = " ".join(question.strip().split())
    if len(cleaned) <= 80:
        return cleaned

    return f"{cleaned[:77].rstrip()}..."


def _build_extractive_fallback_answer(source: FinalizedCitationSource) -> str:
    excerpt = " ".join(source.chunk.content.split())
    if len(excerpt) > 700:
        excerpt = f"{excerpt[:697].rstrip()}..."

    return (
        "The chat model is temporarily unavailable, but the retrieved document context "
        f"contains this relevant excerpt: {excerpt} [Source {source.source_number}]"
    )


def _is_not_enough_info_answer(answer: str) -> bool:
    normalized = " ".join(answer.strip().lower().split())
    target = " ".join(NOT_ENOUGH_INFO_MESSAGE.strip().lower().split())
    if normalized == target:
        return True

    return any(pattern.search(normalized) for pattern in NOT_ENOUGH_INFO_PATTERNS)


def _should_attempt_soft_confidence_answer(retrieval_result) -> bool:
    if not retrieval_result.chunks:
        return False

    threshold = retrieval_result.debug.threshold
    best_score = retrieval_result.chunks[0].combined_score
    if threshold is None:
        return True

    return best_score >= max(0.30, threshold - 0.12)


def _extract_cited_source_numbers(answer: str, max_source_number: int) -> list[int]:
    cited_numbers: list[int] = []
    seen_numbers: set[int] = set()

    for match in SOURCE_BRACKET_PATTERN.finditer(answer):
        number_segment = match.group(1)
        for raw_number in re.findall(r"\d+", number_segment):
            number = int(raw_number)
            if number < 1 or number > max_source_number or number in seen_numbers:
                continue
            seen_numbers.add(number)
            cited_numbers.append(number)

    return cited_numbers


def _deduplicate_citation_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    deduplicated: dict[
        tuple[UUID, int | None, str | None], tuple[int, list[RetrievedChunk]]
    ] = {}

    for index, chunk in enumerate(chunks):
        dedupe_key = (
            chunk.document_id,
            chunk.page_number,
            chunk.section_title.strip() if chunk.section_title else None,
        )
        existing = deduplicated.get(dedupe_key)
        if existing is None:
            deduplicated[dedupe_key] = (index, [chunk])
            continue

        existing[1].append(chunk)

    return [
        _merge_citation_chunk_group(group)
        for _, group in sorted(
            deduplicated.values(),
            key=lambda item: item[0],
        )
    ]


def _merge_citation_chunk_group(chunks: list[RetrievedChunk]) -> RetrievedChunk:
    if len(chunks) == 1:
        return chunks[0]

    primary_chunk = max(
        chunks,
        key=lambda chunk: (
            chunk.combined_score,
            chunk.vector_score or 0.0,
            chunk.keyword_score or 0.0,
        ),
    )
    ordered_chunks = sorted(
        chunks,
        key=lambda chunk: (
            chunk.page_number if chunk.page_number is not None else -1,
            chunk.chunk_index,
        ),
    )

    merged_content_parts: list[str] = []
    seen_content: set[str] = set()
    for chunk in ordered_chunks:
        content = chunk.content.strip()
        if not content:
            continue
        normalized_content = " ".join(content.split())
        if normalized_content in seen_content:
            continue
        seen_content.add(normalized_content)
        merged_content_parts.append(content)

    merged_metadata = dict(primary_chunk.metadata)
    merged_metadata["merged_chunk_count"] = len(chunks)
    merged_metadata["merged_chunk_ids"] = [
        str(chunk.chunk_id) for chunk in ordered_chunks
    ]

    return primary_chunk.model_copy(
        update={
            "content": "\n\n".join(merged_content_parts) or primary_chunk.content,
            "chunk_index": min(chunk.chunk_index for chunk in ordered_chunks),
            "token_count": sum(chunk.token_count or 0 for chunk in ordered_chunks)
            or primary_chunk.token_count,
            "vector_score": max(
                (
                    chunk.vector_score
                    for chunk in chunks
                    if chunk.vector_score is not None
                ),
                default=primary_chunk.vector_score,
            ),
            "keyword_score": max(
                (
                    chunk.keyword_score
                    for chunk in chunks
                    if chunk.keyword_score is not None
                ),
                default=primary_chunk.keyword_score,
            ),
            "combined_score": max(chunk.combined_score for chunk in chunks),
            "metadata": merged_metadata,
        }
    )


def _finalize_public_sources(
    chunks: list[RetrievedChunk],
) -> list[FinalizedCitationSource]:
    return [
        FinalizedCitationSource(source_number=index, chunk=chunk)
        for index, chunk in enumerate(_deduplicate_citation_chunks(chunks), start=1)
    ]


def _select_public_citation_sources(
    *,
    answer: str,
    finalized_sources: list[FinalizedCitationSource],
) -> list[FinalizedCitationSource]:
    if not finalized_sources:
        return []

    cited_source_numbers = _extract_cited_source_numbers(answer, len(finalized_sources))
    if cited_source_numbers:
        cited_numbers_lookup = set(cited_source_numbers)
        return [
            source
            for source in finalized_sources
            if source.source_number in cited_numbers_lookup
        ]

    return finalized_sources


def _renumber_answer_citations(
    answer: str,
    source_number_map: dict[int, int],
) -> str:
    if not source_number_map:
        return answer

    def replace_match(match: re.Match[str]) -> str:
        raw_numbers = re.findall(r"\d+", match.group(1))
        remapped_numbers: list[str] = []
        seen: set[int] = set()
        for raw_number in raw_numbers:
            original = int(raw_number)
            updated = source_number_map.get(original)
            if updated is None or updated in seen:
                continue
            seen.add(updated)
            remapped_numbers.append(str(updated))

        if not remapped_numbers:
            return ""

        label = "Source" if len(remapped_numbers) == 1 else "Sources"
        return f"[{label} {', '.join(remapped_numbers)}]"

    return " ".join(SOURCE_BRACKET_PATTERN.sub(replace_match, answer).split())


def _finalize_public_citations_for_response(
    *,
    answer: str,
    finalized_sources: list[FinalizedCitationSource],
) -> tuple[str, list[FinalizedCitationSource]]:
    selected_sources = _select_public_citation_sources(
        answer=answer,
        finalized_sources=finalized_sources,
    )
    if not selected_sources:
        return answer, []

    renumbered_sources: list[FinalizedCitationSource] = []
    source_number_map: dict[int, int] = {}
    for index, source in enumerate(selected_sources, start=1):
        source_number_map[source.source_number] = index
        renumbered_sources.append(
            FinalizedCitationSource(source_number=index, chunk=source.chunk)
        )

    return _renumber_answer_citations(answer, source_number_map), renumbered_sources


def _build_prompt_finalized_sources(
    *,
    finalized_sources: list[FinalizedCitationSource],
    prompt_used_chunks: list[RetrievedChunk],
) -> list[FinalizedCitationSource]:
    source_chunks_by_id = {
        source.chunk.chunk_id: source.chunk for source in finalized_sources
    }
    prompt_sources: list[FinalizedCitationSource] = []
    seen_chunk_ids: set[UUID] = set()

    for index, prompt_chunk in enumerate(prompt_used_chunks, start=1):
        if prompt_chunk.chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(prompt_chunk.chunk_id)
        base_chunk = source_chunks_by_id.get(prompt_chunk.chunk_id)
        merged_chunk = (
            prompt_chunk
            if base_chunk is None
            else base_chunk.model_copy(update={"content": prompt_chunk.content})
        )
        prompt_sources.append(
            FinalizedCitationSource(
                source_number=index,
                chunk=merged_chunk,
            )
        )

    return prompt_sources


def _tokenize_answer_text(value: str) -> set[str]:
    return {
        token for token in ANSWER_TOKEN_PATTERN.findall(value.lower()) if len(token) > 2
    }


def _strip_all_source_citations(answer: str) -> str:
    return SOURCE_BRACKET_PATTERN.sub("", answer).strip()


def _clean_answer_spacing(value: str) -> str:
    collapsed = " ".join(value.split())
    return re.sub(r"\s+([.,;:!?])", r"\1", collapsed).strip()


def _split_answer_into_citation_segments(answer: str) -> list[str]:
    paragraph_segments = [
        segment.strip() for segment in re.split(r"\n\s*\n+", answer) if segment.strip()
    ]
    if len(paragraph_segments) > 1:
        return paragraph_segments

    sentence_segments = [
        segment.strip()
        for segment in re.split(r"(?<=[.!?])\s+(?=[A-Z])", answer)
        if segment.strip()
    ]
    return sentence_segments or paragraph_segments


CAPITALIZED_ENTITY_RE = re.compile(
    r"[A-Z][a-zA-Z-]+(?:\s+(?:[a-z]{2,}\s+)*[A-Z][a-zA-Z-]+)+(?:\s*\([A-Z]+\))?"
)


def _extract_mentioned_entities(value: str) -> list[str]:
    normalized = " ".join(value.split())
    seen: set[str] = set()
    entities: list[str] = []
    for match in CAPITALIZED_ENTITY_RE.finditer(normalized):
        entity = match.group().strip()
        if entity and entity not in seen:
            seen.add(entity)
            entities.append(entity)
    return entities


def _resolve_segment_region_context(
    *,
    segment: str,
    active_region_context: list[str],
) -> list[str]:
    explicit_regions = _extract_mentioned_entities(segment)
    if explicit_regions:
        return explicit_regions

    if REGION_CONTEXT_REFERENCE_PATTERN.search(segment):
        return active_region_context

    return []


def _score_source_support_for_segment(
    *,
    segment: str,
    source: FinalizedCitationSource,
    region_context: list[str] | None = None,
) -> float:
    segment_tokens = _tokenize_answer_text(segment)
    source_text = " ".join(
        filter(
            None,
            [
                source.chunk.section_title,
                source.chunk.subsection_title,
                source.chunk.content,
            ],
        )
    )
    source_tokens = _tokenize_answer_text(source_text)
    overlap = len(segment_tokens & source_tokens)
    segment_numbers = set(ANSWER_NUMBER_PATTERN.findall(segment))
    source_numbers = set(ANSWER_NUMBER_PATTERN.findall(source_text))
    numeric_overlap = len(segment_numbers & source_numbers)
    score = float(overlap) + (numeric_overlap * 1.4)

    source_text_lower = source_text.lower()
    segment_lower = segment.lower()
    effective_region_context = region_context or []
    if effective_region_context:
        matching_region_count = sum(
            1
            for region in effective_region_context
            if region.lower() in source_text_lower
        )
        if matching_region_count:
            score += 1.4 * matching_region_count
            missing_region_count = max(
                len(effective_region_context) - matching_region_count, 0
            )
            if matching_region_count == len(effective_region_context):
                score += 1.6
            if missing_region_count:
                score -= 1.1 * missing_region_count
        else:
            score -= 3.0
    return score


def _build_source_citation_label(source_numbers: list[int]) -> str:
    label = "Source" if len(source_numbers) == 1 else "Sources"
    return f"[{label} {', '.join(str(number) for number in source_numbers)}]"


def _select_backend_citation_sources_for_segment(
    *,
    segment: str,
    finalized_sources: list[FinalizedCitationSource],
    region_context: list[str] | None = None,
) -> list[FinalizedCitationSource]:
    segment_lower = segment.lower()
    if any(
        phrase in segment_lower
        for phrase in (
            "less certain",
            "remains uncertain",
            "not directly stated",
            "not directly state",
            "not clearly stated",
            "not clearly specify",
            "not enough information",
            "does not provide enough information",
        )
    ):
        return []

    scored_sources = sorted(
        (
            (
                _score_source_support_for_segment(segment=segment, source=source),
                source,
            )
            for source in finalized_sources
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    if not scored_sources or scored_sources[0][0] <= 0:
        return []

    selected = [scored_sources[0][1]]
    if len(scored_sources) < 2:
        return selected

    second_score, second_source = scored_sources[1]
    multi_fact_segment = (
        ";" in segment
        or " while " in segment.lower()
        or " whereas " in segment.lower()
        or " respectively" in segment.lower()
        or " tie " in f" {segment.lower()} "
    )
    if multi_fact_segment and second_score >= max(scored_sources[0][0] * 0.82, 2.5):
        selected.append(second_source)

    return selected


def _apply_backend_citation_labels(
    *,
    answer: str,
    finalized_sources: list[FinalizedCitationSource],
) -> tuple[str, list[FinalizedCitationSource]]:
    if not answer.strip() or not finalized_sources:
        return answer, []

    stripped_answer = _strip_all_source_citations(answer)
    if not stripped_answer:
        return answer, []

    segments = _split_answer_into_citation_segments(stripped_answer)
    if not segments:
        return answer, []

    labeled_segments: list[str] = []
    selected_source_numbers: list[int] = []
    seen_source_numbers: set[int] = set()
    active_region_context: list[str] = []

    for segment in segments:
        region_context = _resolve_segment_region_context(
            segment=segment,
            active_region_context=active_region_context,
        )
        if region_context:
            active_region_context = region_context
        selected_sources = _select_backend_citation_sources_for_segment(
            segment=segment,
            finalized_sources=finalized_sources,
            region_context=region_context,
        )
        if not selected_sources:
            labeled_segments.append(segment)
            continue

        source_numbers = [source.source_number for source in selected_sources]
        for source_number in source_numbers:
            if source_number not in seen_source_numbers:
                seen_source_numbers.add(source_number)
                selected_source_numbers.append(source_number)

        labeled_segments.append(
            f"{segment.rstrip()} {_build_source_citation_label(source_numbers)}"
        )

    if not selected_source_numbers:
        first_source = finalized_sources[0]
        selected_source_numbers.append(first_source.source_number)
        labeled_segments[-1] = (
            f"{labeled_segments[-1].rstrip()} "
            f"{_build_source_citation_label([first_source.source_number])}"
        )

    return _finalize_public_citations_for_response(
        answer=_clean_answer_spacing("\n\n".join(labeled_segments)),
        finalized_sources=finalized_sources,
    )


def _normalize_answer_validation_text(value: str) -> str:
    return " ".join(value.lower().split())


def _strip_citation_markers(value: str) -> str:
    return SOURCE_BRACKET_PATTERN.sub("", value)


def _select_supporting_sources_for_segment(
    *,
    segment: str,
    finalized_sources: list[FinalizedCitationSource],
) -> list[FinalizedCitationSource]:
    cited_numbers = _extract_cited_source_numbers(segment, len(finalized_sources))
    if not cited_numbers:
        return finalized_sources

    cited_lookup = set(cited_numbers)
    return [
        source for source in finalized_sources if source.source_number in cited_lookup
    ]


def _collect_segment_faithfulness_issues(
    *,
    segment: str,
    question_numbers: set[str],
    finalized_sources: list[FinalizedCitationSource],
    active_region_context: list[str],
) -> tuple[list[str], list[str]]:
    normalized_segment = _normalize_answer_validation_text(
        _strip_citation_markers(segment)
    )
    if not normalized_segment:
        return [], active_region_context

    region_context = _resolve_segment_region_context(
        segment=normalized_segment,
        active_region_context=active_region_context,
    )
    updated_region_context = region_context or active_region_context
    supporting_sources = _select_supporting_sources_for_segment(
        segment=segment,
        finalized_sources=finalized_sources,
    )
    supporting_text = _normalize_answer_validation_text(
        " ".join(source.chunk.content for source in supporting_sources)
    )
    supporting_numbers = set(ANSWER_NUMBER_PATTERN.findall(supporting_text))
    supporting_entities = _extract_mentioned_entities(supporting_text)
    issues: list[str] = []
    seen_issues: set[str] = set()

    if region_context:
        missing = [
            e
            for e in region_context
            if e.lower() not in [x.lower() for x in supporting_entities]
        ]
        if missing:
            issue = "Unsupported entity claim: the answer ties this statement to a specific entity, but the cited source text does not mention that entity."
            if issue not in seen_issues:
                seen_issues.add(issue)
                issues.append(issue)

    for number in ANSWER_NUMBER_PATTERN.findall(normalized_segment):
        if number in question_numbers:
            continue
        if number in supporting_numbers:
            continue
        issue = f"Unsupported numeric claim: the answer uses '{number}', but the cited source text does not contain that number."
        if issue not in seen_issues:
            seen_issues.add(issue)
            issues.append(issue)

    return issues[:6], updated_region_context


def _find_answer_faithfulness_issues(
    *,
    question: str,
    answer: str,
    finalized_sources: list[FinalizedCitationSource],
) -> list[str]:
    if not answer.strip() or not finalized_sources:
        return []

    segments = [
        segment.strip() for segment in re.split(r"\n\s*\n+", answer) if segment.strip()
    ]
    question_numbers = set(
        ANSWER_NUMBER_PATTERN.findall(
            _normalize_answer_validation_text(_strip_citation_markers(question))
        )
    )

    issues: list[str] = []
    seen_issues: set[str] = set()
    active_region_context: list[str] = []

    for segment in segments:
        segment_issues, active_region_context = _collect_segment_faithfulness_issues(
            segment=segment,
            question_numbers=question_numbers,
            finalized_sources=finalized_sources,
            active_region_context=active_region_context,
        )
        for issue in segment_issues:
            if issue in seen_issues:
                continue
            seen_issues.add(issue)
            issues.append(issue)

    return issues[:6]


def _build_supported_answer_fallback(
    *,
    question: str,
    answer: str,
    finalized_sources: list[FinalizedCitationSource],
) -> str:
    cleaned_answer = _strip_all_source_citations(answer)
    segments = _split_answer_into_citation_segments(cleaned_answer)
    if not segments:
        return NOT_ENOUGH_INFO_MESSAGE

    question_numbers = set(
        ANSWER_NUMBER_PATTERN.findall(
            _normalize_answer_validation_text(_strip_citation_markers(question))
        )
    )
    active_region_context: list[str] = []
    supported_segments: list[str] = []

    for segment in segments:
        segment_issues, active_region_context = _collect_segment_faithfulness_issues(
            segment=segment,
            question_numbers=question_numbers,
            finalized_sources=finalized_sources,
            active_region_context=active_region_context,
        )

        if not segment_issues:
            supported_segments.append(segment.strip())
            continue

    if not supported_segments:
        return NOT_ENOUGH_INFO_MESSAGE

    return _clean_answer_spacing(" ".join(supported_segments))


def _build_answer_correction_messages(
    *,
    question: str,
    answer: str,
    finalized_sources: list[FinalizedCitationSource],
    issues: list[str],
) -> list[dict[str, str]]:
    source_blocks = "\n\n".join(
        _format_context_block(source.source_number, source.chunk)
        for source in finalized_sources
    )
    issue_block = "\n".join(f"- {issue}" for issue in issues)

    return [
        {
            "role": "system",
            "content": (
                "You are correcting a document-grounded answer. "
                "Use only the provided retrieved sources. "
                "Remove or rewrite unsupported claims. "
                "Keep supported claims. "
                "If part of the answer is not directly supported, mark only that part uncertain. "
                "Use plain text, do not use markdown, and keep the same [Source N] citation format."
            ),
        },
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    f"Original question:\n{question}",
                    f"Draft answer:\n{answer}",
                    f"Detected support issues:\n{issue_block}",
                    f"Available sources:\n{source_blocks}",
                    (
                        "Rewrite the answer so every factual claim is directly supported by the sources above. "
                        "Use the exact numbers and rankings from the source text when available. "
                        "Do not expose internal reasoning or labeled parts."
                    ),
                ]
            ),
        },
    ]


def _correct_answer_if_needed(
    *,
    question: str,
    answer: str,
    finalized_sources: list[FinalizedCitationSource],
    settings: Settings,
) -> tuple[str, bool]:
    issues = _find_answer_faithfulness_issues(
        question=question,
        answer=answer,
        finalized_sources=finalized_sources,
    )
    if not issues:
        return answer, False

    correction_messages = _build_answer_correction_messages(
        question=question,
        answer=answer,
        finalized_sources=finalized_sources,
        issues=issues,
    )
    try:
        corrected_response = generate_chat_completion(
            correction_messages,
            settings=settings,
        )
    except DependencyUnavailableError:
        logger.warning(
            "Answer correction could not be completed because the model is unavailable."
        )
        return _build_supported_answer_fallback(
            question=question,
            answer=answer,
            finalized_sources=finalized_sources,
        ), True

    corrected_issues = _find_answer_faithfulness_issues(
        question=question,
        answer=corrected_response.answer,
        finalized_sources=finalized_sources,
    )
    if corrected_issues:
        logger.warning(
            "Answer correction still failed faithfulness validation: %s",
            corrected_issues,
        )
        return _build_supported_answer_fallback(
            question=question,
            answer=corrected_response.answer,
            finalized_sources=finalized_sources,
        ), True

    return corrected_response.answer, True


def _normalize_retrieval_text(value: str) -> str:
    return " ".join(value.lower().split())


def _extract_anchor_regions(chunks: list[RetrievedChunk], limit: int = 2) -> list[str]:
    if not chunks:
        return []

    entity_scores: dict[str, float] = {}
    entity_chunk_counts: dict[str, int] = {}
    examined_chunks = chunks[:8]
    for chunk in examined_chunks:
        haystack = " ".join(
            " ".join(
                filter(
                    None,
                    [
                        chunk.section_title,
                        chunk.subsection_title,
                        chunk.content,
                    ],
                )
            ).split()
        )
        seen_in_chunk: set[str] = set()
        for entity in _extract_mentioned_entities(haystack):
            entity_lower = entity.lower()
            for existing in list(entity_scores.keys()):
                if existing.lower() == entity_lower:
                    entity = existing
                    break
            entity_scores[entity] = (
                entity_scores.get(entity, 0.0) + 1.0 + chunk.combined_score
            )
            if entity not in seen_in_chunk:
                seen_in_chunk.add(entity)
                entity_chunk_counts[entity] = entity_chunk_counts.get(entity, 0) + 1

    num_chunks = len(examined_chunks)
    scored = []
    for entity, score in entity_scores.items():
        if score <= 0:
            continue
        frequency = (
            entity_chunk_counts.get(entity, 0) / num_chunks if num_chunks else 1.0
        )
        adjusted = score * 0.5 if frequency > 0.6 else score
        scored.append((entity, adjusted))

    if not scored:
        return []

    scored.sort(key=lambda item: item[1], reverse=True)
    top_entity, top_score = scored[0]
    selected = [top_entity]
    for entity, score in scored[1:]:
        if len(selected) >= limit:
            break
        if score >= top_score * 0.6:
            selected.append(entity)

    return selected


def _format_anchor_regions(regions: list[str]) -> str:
    if not regions:
        return "that region"
    if len(regions) == 1:
        return regions[0]
    if len(regions) == 2:
        return f"{regions[0]} and {regions[1]}"

    return ", ".join(regions[:-1]) + f", and {regions[-1]}"


def _rewrite_subquery_with_anchor(subquery: str, anchor_regions: list[str]) -> str:
    if not anchor_regions:
        return subquery

    anchor_text = _format_anchor_regions(anchor_regions)
    rewritten = REGION_REFERENCE_PATTERN.sub(anchor_text, subquery)
    if rewritten != subquery:
        return rewritten

    if LOCATION_REFERENCE_PATTERN.search(subquery):
        return LOCATION_REFERENCE_PATTERN.sub(f"in {anchor_text}", subquery)

    if _extract_mentioned_entities(subquery):
        return subquery

    return (
        f"For {anchor_text}, {subquery[0].lower()}{subquery[1:]}"
        if subquery
        else subquery
    )


def _merge_retrieval_chunks(results: list[RetrievalResult]) -> list[RetrievedChunk]:
    merged: dict[UUID, tuple[RetrievedChunk, int, int]] = {}

    for result_index, result in enumerate(results):
        for chunk_index, chunk in enumerate(result.chunks):
            existing = merged.get(chunk.chunk_id)
            if existing is None:
                merged[chunk.chunk_id] = (chunk, 1, result_index * 100 + chunk_index)
                continue

            existing_chunk, support_count, first_seen_order = existing
            merged_chunk = (
                chunk
                if chunk.combined_score > existing_chunk.combined_score
                else existing_chunk
            )
            merged[chunk.chunk_id] = (merged_chunk, support_count + 1, first_seen_order)

    merged_chunks: list[RetrievedChunk] = []
    for chunk, support_count, first_seen_order in merged.values():
        boosted_score = min(
            chunk.combined_score + (0.04 * max(support_count - 1, 0)), 1.0
        )
        merged_chunks.append(
            chunk.model_copy(
                update={
                    "combined_score": round(boosted_score, 6),
                    "metadata": {
                        **chunk.metadata,
                        "support_count": support_count,
                        "first_seen_order": first_seen_order,
                    },
                }
            )
        )

    merged_chunks.sort(
        key=lambda chunk: (
            chunk.metadata.get("support_count", 1),
            chunk.combined_score,
            -(chunk.metadata.get("first_seen_order", 0)),
        ),
        reverse=True,
    )
    return merged_chunks


def _combine_retrieval_results(
    *,
    results: list[RetrievalResult],
    settings: Settings,
) -> RetrievalResult:
    if not results:
        return RetrievalResult(
            retrieval_passed=False,
            chunks=[],
            debug=RetrievalDebugInfo(
                candidate_count=0,
                vector_candidate_count=0,
                keyword_candidate_count=0,
                top_k=settings.retrieval_top_k,
                candidate_k=settings.retrieval_candidate_k,
                threshold=settings.retrieval_score_threshold,
                latency_ms=0,
                vector_weight=settings.vector_search_weight,
                keyword_weight=settings.keyword_search_weight,
                document_filter_count=0,
            ),
        )

    merged_chunks = _merge_retrieval_chunks(results)
    threshold_candidates = [
        result.debug.threshold
        for result in results
        if result.debug.threshold is not None
    ]
    threshold = (
        min(threshold_candidates)
        if threshold_candidates
        else settings.retrieval_score_threshold
    )
    best_score = merged_chunks[0].combined_score if merged_chunks else 0.0
    retrieval_passed = any(result.retrieval_passed for result in results)
    if not retrieval_passed and merged_chunks:
        retrieval_passed = best_score >= max(0.3, (threshold or 0.0) - 0.1)

    return RetrievalResult(
        retrieval_passed=retrieval_passed,
        chunks=merged_chunks,
        debug=RetrievalDebugInfo(
            candidate_count=len(merged_chunks),
            vector_candidate_count=sum(
                result.debug.vector_candidate_count for result in results
            ),
            keyword_candidate_count=sum(
                result.debug.keyword_candidate_count for result in results
            ),
            top_k=max(result.debug.top_k for result in results),
            candidate_k=max(result.debug.candidate_k for result in results),
            threshold=threshold,
            latency_ms=sum(result.debug.latency_ms for result in results),
            vector_weight=settings.vector_search_weight,
            keyword_weight=settings.keyword_search_weight,
            document_filter_count=max(
                result.debug.document_filter_count for result in results
            ),
        ),
    )


def _attempt_re_retrieval(
    *,
    user_id: UUID,
    question: str,
    document_ids: list[UUID] | None,
    session_id: UUID,
    message_id: UUID,
    settings: Settings,
) -> RetrievalResult | None:
    result = retrieve_relevant_chunks(
        user_id=user_id,
        query=question,
        document_ids=document_ids,
        top_k=settings.retrieval_max_top_k,
        candidate_k=settings.retrieval_max_candidate_k,
        threshold=0.0,
        session_id=session_id,
        message_id=message_id,
        original_question=question,
        settings=settings,
        record_log=True,
    )
    if result.chunks:
        return result
    return None


def _retrieve_chat_evidence(
    *,
    user_id: UUID,
    question: str,
    chat_history: list[dict[str, str]],
    document_ids: list[UUID] | None,
    session_id: UUID,
    message_id: UUID,
    settings: Settings,
) -> tuple[RetrievalResult, str, bool]:
    primary_query_result = build_retrieval_query(
        question=question,
        chat_history=chat_history,
        settings=settings,
    )
    primary_result = retrieve_relevant_chunks(
        user_id=user_id,
        query=primary_query_result.retrieval_query,
        document_ids=document_ids,
        top_k=None,
        candidate_k=None,
        threshold=None,
        session_id=session_id,
        message_id=message_id,
        original_question=question,
        settings=settings,
        record_log=True,
    )

    subqueries = _derive_prompt_subqueries(question)
    if len(subqueries) <= 1:
        return (
            primary_result,
            primary_query_result.retrieval_query,
            primary_query_result.history_used,
        )

    subquery_results: list[RetrievalResult] = []
    anchor_regions: list[str] = []
    history_used_for_any_subquery = primary_query_result.history_used

    for index, subquery in enumerate(subqueries):
        rewritten_subquery = _rewrite_subquery_with_anchor(subquery, anchor_regions)
        subquery_query_result = build_retrieval_query(
            question=rewritten_subquery,
            chat_history=chat_history,
            settings=settings,
        )
        history_used_for_any_subquery = (
            history_used_for_any_subquery or subquery_query_result.history_used
        )
        subquery_result = retrieve_relevant_chunks(
            user_id=user_id,
            query=subquery_query_result.retrieval_query,
            document_ids=document_ids,
            top_k=max(4, settings.retrieval_top_k),
            candidate_k=max(
                settings.retrieval_candidate_k * 2,
                settings.retrieval_max_candidate_k // 2,
            ),
            threshold=max(0.28, settings.retrieval_score_threshold - 0.08),
            session_id=session_id,
            message_id=message_id,
            original_question=question,
            settings=settings,
            record_log=False,
        )
        subquery_results.append(subquery_result)
        if not anchor_regions:
            anchor_regions = _extract_anchor_regions(subquery_result.chunks)

    combined_result = _combine_retrieval_results(
        results=subquery_results + [primary_result],
        settings=settings,
    )
    return (
        combined_result,
        primary_query_result.retrieval_query,
        history_used_for_any_subquery,
    )


def _create_chat_session_record(
    *,
    user_id: UUID,
    title: str | None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    cleaned_title = _clean_title(title)

    def callback() -> dict[str, Any]:
        with database_connection(settings) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO public.chat_sessions (id, user_id, title)
                    VALUES (%s, %s, %s)
                    RETURNING *
                    """,
                    (uuid4(), user_id, cleaned_title),
                )
                row = cursor.fetchone()
            connection.commit()

        return row

    return _run_db_operation("create_chat_session_record", callback)


def _build_chat_session_summary(row: dict[str, Any]) -> ChatSessionSummary:
    return ChatSessionSummary(
        session_id=row["id"],
        title=row.get("title"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _publish_chat_session_upsert(user_id: UUID, row: dict[str, Any] | None) -> None:
    if row is None:
        return

    chat_realtime_broker.publish_to_user(
        user_id,
        {
            "type": "chat.session.upsert",
            "session": _build_chat_session_summary(row).model_dump(mode="json"),
        },
    )


def _publish_chat_session_snapshot(user_id: UUID, session_id: UUID) -> None:
    row = _get_chat_session_row(session_id, user_id)
    _publish_chat_session_upsert(user_id, row)


def _build_chat_message_record(
    *,
    message_row: dict[str, Any],
    citations: list[ChatMessageCitation] | None = None,
) -> ChatMessageRecord:
    return ChatMessageRecord(
        message_id=message_row["id"],
        session_id=message_row["session_id"],
        role=message_row["role"],
        content=message_row["content"],
        model_used=message_row.get("model_used"),
        prompt_tokens=message_row.get("prompt_tokens"),
        completion_tokens=message_row.get("completion_tokens"),
        estimated_cost=float(message_row["estimated_cost"])
        if message_row.get("estimated_cost") is not None
        else None,
        created_at=message_row["created_at"],
        citations=citations or [],
    )


def _publish_chat_message_created(
    *,
    user_id: UUID,
    session_id: UUID,
    message: ChatMessageRecord,
) -> None:
    chat_realtime_broker.publish_to_user(
        user_id,
        {
            "type": "chat.message.created",
            "session_id": str(session_id),
            "message": message.model_dump(mode="json"),
        },
    )


def create_chat_session(
    *,
    user_id: UUID,
    title: str | None = None,
    ip_address: str | None = None,
) -> ChatSessionSummary:
    row = _create_chat_session_record(user_id=user_id, title=title)
    session_summary = _build_chat_session_summary(row)
    record_audit_log_sync(
        action="chat_session_created",
        user_id=user_id,
        resource_type="chat_session",
        resource_id=row["id"],
        metadata={"title": row.get("title")},
        ip_address=ip_address,
    )
    _publish_chat_session_upsert(user_id, row)

    return session_summary


def list_chat_sessions(user_id: UUID) -> list[ChatSessionSummary]:
    def callback() -> list[dict[str, Any]]:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, title, created_at, updated_at
                    FROM public.chat_sessions
                    WHERE user_id = %s
                    ORDER BY updated_at DESC, created_at DESC
                    """,
                    (user_id,),
                )
                return cursor.fetchall()

    rows = _run_db_operation("list_chat_sessions", callback)
    return [
        ChatSessionSummary(
            session_id=row["id"],
            title=row.get("title"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def delete_chat_session(
    *,
    session_id: UUID,
    user_id: UUID,
    ip_address: str | None = None,
) -> ChatSessionDeleteResponse:
    def callback() -> UUID | None:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM public.chat_sessions
                    WHERE id = %s
                      AND user_id = %s
                    RETURNING id
                    """,
                    (session_id, user_id),
                )
                row = cursor.fetchone()
            connection.commit()

        return row["id"] if row else None

    deleted_session_id = _run_db_operation("delete_chat_session", callback)
    if deleted_session_id is None:
        raise NotFoundError("Chat session not found.")

    record_audit_log_sync(
        action="chat_session_deleted",
        user_id=user_id,
        resource_type="chat_session",
        resource_id=deleted_session_id,
        metadata={},
        ip_address=ip_address,
    )
    chat_realtime_broker.publish_to_user(
        user_id,
        {
            "type": "chat.session.deleted",
            "session_id": str(deleted_session_id),
        },
    )

    return ChatSessionDeleteResponse(session_id=deleted_session_id, deleted=True)


def _get_chat_session_row(session_id: UUID, user_id: UUID) -> dict[str, Any] | None:
    def callback() -> dict[str, Any] | None:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM public.chat_sessions
                    WHERE id = %s
                      AND user_id = %s
                    LIMIT 1
                    """,
                    (session_id, user_id),
                )
                return cursor.fetchone()

    return _run_db_operation("get_chat_session_row", callback)


def _create_chat_message_record(
    *,
    session_id: UUID,
    user_id: UUID,
    role: str,
    content: str,
    model_used: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    estimated_cost: float | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    def callback() -> dict[str, Any]:
        with database_connection(settings) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO public.chat_messages (
                        id,
                        session_id,
                        user_id,
                        role,
                        content,
                        model_used,
                        prompt_tokens,
                        completion_tokens,
                        estimated_cost
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        uuid4(),
                        session_id,
                        user_id,
                        role,
                        content,
                        model_used,
                        prompt_tokens,
                        completion_tokens,
                        estimated_cost,
                    ),
                )
                row = cursor.fetchone()
                cursor.execute(
                    """
                    UPDATE public.chat_sessions
                    SET updated_at = timezone('utc', now())
                    WHERE id = %s
                      AND user_id = %s
                    """,
                    (session_id, user_id),
                )
            connection.commit()

        return row

    return _run_db_operation("create_chat_message_record", callback)


def _list_recent_chat_history(
    *,
    session_id: UUID,
    user_id: UUID,
    exclude_message_id: UUID | None = None,
    settings: Settings | None = None,
) -> list[dict[str, str]]:
    current_settings = settings or get_settings()

    def callback() -> list[dict[str, Any]]:
        with database_connection(current_settings) as connection:
            with connection.cursor() as cursor:
                exclusion_sql = ""
                params: list[Any] = [session_id, user_id]
                if exclude_message_id is not None:
                    exclusion_sql = "AND id <> %s"
                    params.append(exclude_message_id)
                params.append(current_settings.max_chat_history_messages)
                cursor.execute(
                    f"""
                    SELECT role, content
                    FROM public.chat_messages
                    WHERE session_id = %s
                      AND user_id = %s
                      {exclusion_sql}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    params,
                )
                rows = cursor.fetchall()

        rows.reverse()
        return rows

    rows = _run_db_operation("list_recent_chat_history", callback)
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def _store_message_citations(
    *,
    message_id: UUID,
    sources: list[FinalizedCitationSource],
) -> None:
    if not sources:
        return

    supports_source_number = _message_citations_supports_source_number()

    def callback() -> None:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                if supports_source_number:
                    cursor.executemany(
                        """
                        INSERT INTO public.message_citations (
                            id,
                            message_id,
                            chunk_id,
                            document_id,
                            source_number,
                            source_file,
                            page_number,
                            section_title,
                            similarity_score
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            (
                                uuid4(),
                                message_id,
                                source.chunk.chunk_id,
                                source.chunk.document_id,
                                source.source_number,
                                source.chunk.source_file,
                                source.chunk.page_number,
                                source.chunk.section_title,
                                source.chunk.combined_score,
                            )
                            for source in sources
                        ],
                    )
                else:
                    cursor.executemany(
                        """
                        INSERT INTO public.message_citations (
                            id,
                            message_id,
                            chunk_id,
                            document_id,
                            source_file,
                            page_number,
                            section_title,
                            similarity_score
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            (
                                uuid4(),
                                message_id,
                                source.chunk.chunk_id,
                                source.chunk.document_id,
                                source.chunk.source_file,
                                source.chunk.page_number,
                                source.chunk.section_title,
                                source.chunk.combined_score,
                            )
                            for source in sources
                        ],
                    )
            connection.commit()

    _run_db_operation("store_message_citations", callback)


def list_chat_messages(session_id: UUID, user_id: UUID) -> list[ChatMessageRecord]:
    if _get_chat_session_row(session_id, user_id) is None:
        raise NotFoundError("Chat session not found.")

    supports_source_number = _message_citations_supports_source_number()

    def callback() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, session_id, role, content, model_used, prompt_tokens, completion_tokens, estimated_cost, created_at
                    FROM public.chat_messages
                    WHERE session_id = %s
                      AND user_id = %s
                    ORDER BY created_at ASC, id ASC
                    """,
                    (session_id, user_id),
                )
                messages = cursor.fetchall()
                if supports_source_number:
                    cursor.execute(
                        """
                        SELECT
                            message_id,
                            chunk_id,
                            document_id,
                            source_number,
                            source_file,
                            page_number,
                            section_title,
                            similarity_score
                        FROM public.message_citations
                        WHERE message_id = ANY(%s)
                        ORDER BY message_id ASC, source_number ASC, created_at ASC, id ASC
                        """,
                        ([message["id"] for message in messages] or [uuid4()],),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT
                            message_id,
                            chunk_id,
                            document_id,
                            ROW_NUMBER() OVER (
                                PARTITION BY message_id
                                ORDER BY created_at ASC, id ASC
                            ) AS source_number,
                            source_file,
                            page_number,
                            section_title,
                            similarity_score
                        FROM public.message_citations
                        WHERE message_id = ANY(%s)
                        ORDER BY message_id ASC, source_number ASC, created_at ASC, id ASC
                        """,
                        ([message["id"] for message in messages] or [uuid4()],),
                    )
                citations = cursor.fetchall()

        return messages, citations

    messages, citations = _run_db_operation("list_chat_messages", callback)
    citations_by_message: dict[UUID, list[ChatMessageCitation]] = {}
    for citation in citations:
        citations_by_message.setdefault(citation["message_id"], []).append(
            ChatMessageCitation(
                source_number=citation["source_number"],
                chunk_id=citation["chunk_id"],
                document_id=citation["document_id"],
                source_file=citation["source_file"],
                page_number=citation["page_number"],
                section_title=citation["section_title"],
                similarity_score=float(citation["similarity_score"])
                if citation["similarity_score"] is not None
                else None,
            )
        )

    return [
        ChatMessageRecord(
            message_id=message["id"],
            session_id=message["session_id"],
            role=message["role"],
            content=message["content"],
            model_used=message["model_used"],
            prompt_tokens=message["prompt_tokens"],
            completion_tokens=message["completion_tokens"],
            estimated_cost=float(message["estimated_cost"])
            if message["estimated_cost"] is not None
            else None,
            created_at=message["created_at"],
            citations=citations_by_message.get(message["id"], []),
        )
        for message in messages
    ]


def _build_debug_info(
    *,
    original_question: str,
    retrieval_query: str,
    history_used_for_rewrite: bool,
    chunks: list[RetrievedChunk],
    preview_chars: int,
    retrieval_debug,
) -> ChatDebugInfo:
    return ChatDebugInfo(
        original_question=original_question,
        retrieval_query=retrieval_query,
        history_used_for_rewrite=history_used_for_rewrite,
        retrieval=retrieval_debug,
        chunks=[
            ChatDebugChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                source_file=chunk.source_file,
                section_title=chunk.section_title,
                subsection_title=chunk.subsection_title,
                combined_score=chunk.combined_score,
                vector_score=chunk.vector_score,
                keyword_score=chunk.keyword_score,
                content_preview=(
                    chunk.content
                    if len(chunk.content) <= preview_chars
                    else f"{chunk.content[:preview_chars].rstrip()}..."
                ),
            )
            for chunk in chunks
        ],
    )


def answer_chat_question(
    *,
    user_id: UUID,
    question: str,
    session_id: UUID | None = None,
    document_ids: list[UUID] | None = None,
    debug: bool = False,
    ip_address: str | None = None,
    settings: Settings | None = None,
) -> ChatResponse:
    current_settings = settings or get_settings()
    cleaned_question = question.strip()
    if not cleaned_question:
        raise AppError("Question must not be empty.", status_code=400)
    logger.info(
        "answer_chat_question: user_id=%s question=%s document_ids=%s session_id=%s",
        user_id,
        cleaned_question[:80],
        document_ids,
        session_id,
    )
    if len(cleaned_question) > current_settings.max_question_chars:
        raise AppError(
            f"Question exceeds the maximum allowed length of {current_settings.max_question_chars} characters.",
            status_code=400,
        )

    active_session_id: UUID
    if session_id is None:
        session = create_chat_session(
            user_id=user_id,
            title=_default_session_title(cleaned_question),
            ip_address=ip_address,
        )
        active_session_id = session.session_id
    else:
        session_row = _get_chat_session_row(session_id, user_id)
        if session_row is None:
            raise NotFoundError("Chat session not found.")
        active_session_id = session_id

    user_message = _create_chat_message_record(
        session_id=active_session_id,
        user_id=user_id,
        role="user",
        content=cleaned_question,
        settings=current_settings,
    )
    _publish_chat_session_snapshot(user_id, active_session_id)
    record_audit_log_sync(
        action="chat_question_received",
        user_id=user_id,
        resource_type="chat_session",
        resource_id=active_session_id,
        metadata={"message_id": str(user_message["id"])},
        ip_address=ip_address,
    )
    user_message_record = _build_chat_message_record(message_row=user_message)
    _publish_chat_message_created(
        user_id=user_id,
        session_id=active_session_id,
        message=user_message_record,
    )

    chat_history = _list_recent_chat_history(
        session_id=active_session_id,
        user_id=user_id,
        exclude_message_id=user_message["id"],
        settings=current_settings,
    )
    retrieval_result, retrieval_query, history_used_for_rewrite = (
        _retrieve_chat_evidence(
            user_id=user_id,
            question=cleaned_question,
            chat_history=chat_history,
            document_ids=document_ids,
            session_id=active_session_id,
            message_id=user_message["id"],
            settings=current_settings,
        )
    )
    best_score = (
        retrieval_result.chunks[0].combined_score if retrieval_result.chunks else 0.0
    )
    logger.info(
        "Retrieval result: passed=%s best_score=%s threshold=%s chunks=%s",
        retrieval_result.retrieval_passed,
        best_score,
        retrieval_result.debug.threshold,
        len(retrieval_result.chunks),
    )
    finalized_prompt_sources = _finalize_public_sources(retrieval_result.chunks)
    debug_payload = (
        _build_debug_info(
            original_question=cleaned_question,
            retrieval_query=retrieval_query,
            history_used_for_rewrite=history_used_for_rewrite,
            chunks=retrieval_result.chunks,
            preview_chars=current_settings.retrieval_preview_chars,
            retrieval_debug=retrieval_result.debug,
        )
        if debug
        else None
    )

    if not retrieval_result.retrieval_passed and _should_attempt_soft_confidence_answer(
        retrieval_result
    ):
        logger.info(
            "Path A: soft confidence attempt (best_score=%s, threshold=%s)",
            best_score,
            retrieval_result.debug.threshold,
        )
        prompt = build_grounded_prompt(
            question=cleaned_question,
            retrieved_chunks=[source.chunk for source in finalized_prompt_sources],
            settings=current_settings,
        )
        prompt_finalized_sources = _build_prompt_finalized_sources(
            finalized_sources=finalized_prompt_sources,
            prompt_used_chunks=prompt.used_chunks,
        )
        try:
            llm_response = generate_chat_completion(
                prompt.messages, settings=current_settings
            )
        except DependencyUnavailableError:
            llm_response = None

        if llm_response is not None:
            candidate_answer = llm_response.answer
            if not _is_not_enough_info_answer(candidate_answer):
                candidate_answer, _ = _correct_answer_if_needed(
                    question=cleaned_question,
                    answer=candidate_answer,
                    finalized_sources=prompt_finalized_sources,
                    settings=current_settings,
                )

            if not _is_not_enough_info_answer(candidate_answer):
                finalized_answer, public_citation_sources = (
                    _apply_backend_citation_labels(
                        answer=candidate_answer,
                        finalized_sources=prompt_finalized_sources,
                    )
                )
                assistant_message = _create_chat_message_record(
                    session_id=active_session_id,
                    user_id=user_id,
                    role="assistant",
                    content=finalized_answer,
                    model_used=llm_response.model_used,
                    prompt_tokens=llm_response.usage.prompt_tokens,
                    completion_tokens=llm_response.usage.completion_tokens,
                    estimated_cost=None,
                    settings=current_settings,
                )
                if public_citation_sources:
                    _store_message_citations(
                        message_id=assistant_message["id"],
                        sources=public_citation_sources,
                    )
                record_audit_log_sync(
                    action="chat_answer_created",
                    user_id=user_id,
                    resource_type="chat_message",
                    resource_id=assistant_message["id"],
                    metadata={
                        "model_used": llm_response.model_used,
                        "citation_count": len(public_citation_sources),
                        "context_chunk_count": len(prompt.used_chunks),
                        "retrieval_passed": True,
                        "soft_confidence": True,
                    },
                    ip_address=ip_address,
                )
                assistant_message_record = ChatMessageRecord(
                    message_id=assistant_message["id"],
                    session_id=active_session_id,
                    role="assistant",
                    content=finalized_answer,
                    model_used=llm_response.model_used,
                    prompt_tokens=llm_response.usage.prompt_tokens,
                    completion_tokens=llm_response.usage.completion_tokens,
                    estimated_cost=None,
                    created_at=assistant_message["created_at"],
                    citations=[
                        ChatMessageCitation(
                            source_number=source.source_number,
                            chunk_id=source.chunk.chunk_id,
                            document_id=source.chunk.document_id,
                            source_file=source.chunk.source_file,
                            page_number=source.chunk.page_number,
                            section_title=source.chunk.section_title,
                            similarity_score=source.chunk.combined_score,
                        )
                        for source in public_citation_sources
                    ],
                )
                _publish_chat_session_snapshot(user_id, active_session_id)
                _publish_chat_message_created(
                    user_id=user_id,
                    session_id=active_session_id,
                    message=assistant_message_record,
                )
                return ChatResponse(
                    session_id=active_session_id,
                    answer=finalized_answer,
                    sources=[
                        {
                            "source_number": source.source_number,
                            "chunk_id": source.chunk.chunk_id,
                            "document_id": source.chunk.document_id,
                            "source_file": source.chunk.source_file,
                            "page_number": source.chunk.page_number,
                            "section_title": source.chunk.section_title,
                            "subsection_title": source.chunk.subsection_title,
                            "chunk_index": source.chunk.chunk_index,
                            "score": source.chunk.combined_score,
                        }
                        for source in public_citation_sources
                    ],
                    model_used=llm_response.model_used,
                    retrieval_passed=True,
                    user_message=user_message_record,
                    assistant_message=assistant_message_record,
                    debug=debug_payload,
                )

    if not retrieval_result.retrieval_passed:
        logger.info(
            "Path B: re-retrieval attempt (best_score=%s, threshold=%s)",
            best_score,
            retrieval_result.debug.threshold,
        )
        re_result = _attempt_re_retrieval(
            user_id=user_id,
            question=cleaned_question,
            document_ids=document_ids,
            session_id=active_session_id,
            message_id=user_message["id"],
            settings=current_settings,
        )
        if re_result is not None:
            retrieval_result = re_result
            finalized_prompt_sources = _finalize_public_sources(retrieval_result.chunks)
            debug_payload = (
                _build_debug_info(
                    original_question=cleaned_question,
                    retrieval_query=cleaned_question,
                    history_used_for_rewrite=False,
                    chunks=retrieval_result.chunks,
                    preview_chars=current_settings.retrieval_preview_chars,
                    retrieval_debug=retrieval_result.debug,
                )
                if debug
                else None
            )
            record_audit_log_sync(
                action="re_retrieval_attempted",
                user_id=user_id,
                resource_type="chat_session",
                resource_id=active_session_id,
                metadata={
                    "message_id": str(user_message["id"]),
                    "candidate_count": retrieval_result.debug.candidate_count,
                    "threshold": retrieval_result.debug.threshold,
                },
                ip_address=ip_address,
            )

    if not retrieval_result.retrieval_passed:
        assistant_message = _create_chat_message_record(
            session_id=active_session_id,
            user_id=user_id,
            role="assistant",
            content=NOT_ENOUGH_INFO_MESSAGE,
            settings=current_settings,
        )
        record_audit_log_sync(
            action="retrieval_failed_low_confidence",
            user_id=user_id,
            resource_type="chat_session",
            resource_id=active_session_id,
            metadata={
                "message_id": str(assistant_message["id"]),
                "candidate_count": retrieval_result.debug.candidate_count,
                "threshold": retrieval_result.debug.threshold,
            },
            ip_address=ip_address,
        )
        record_audit_log_sync(
            action="chat_answer_created",
            user_id=user_id,
            resource_type="chat_message",
            resource_id=assistant_message["id"],
            metadata={"retrieval_passed": False},
            ip_address=ip_address,
        )
        assistant_message_record = ChatMessageRecord(
            message_id=assistant_message["id"],
            session_id=active_session_id,
            role="assistant",
            content=NOT_ENOUGH_INFO_MESSAGE,
            model_used=None,
            prompt_tokens=None,
            completion_tokens=None,
            estimated_cost=None,
            created_at=assistant_message["created_at"],
            citations=[],
        )
        _publish_chat_session_snapshot(user_id, active_session_id)
        _publish_chat_message_created(
            user_id=user_id,
            session_id=active_session_id,
            message=assistant_message_record,
        )
        return ChatResponse(
            session_id=active_session_id,
            answer=NOT_ENOUGH_INFO_MESSAGE,
            sources=[],
            model_used=None,
            retrieval_passed=False,
            user_message=user_message_record,
            assistant_message=assistant_message_record,
            debug=debug_payload,
        )

    prompt = build_grounded_prompt(
        question=cleaned_question,
        retrieved_chunks=[source.chunk for source in finalized_prompt_sources],
        settings=current_settings,
    )
    prompt_finalized_sources = _build_prompt_finalized_sources(
        finalized_sources=finalized_prompt_sources,
        prompt_used_chunks=prompt.used_chunks,
    )

    try:
        llm_response = generate_chat_completion(
            prompt.messages, settings=current_settings
        )
    except DependencyUnavailableError as exc:
        record_audit_log_sync(
            action="llm_call_failed",
            user_id=user_id,
            resource_type="chat_session",
            resource_id=active_session_id,
            metadata={"message_id": str(user_message["id"]), "reason": exc.detail},
            ip_address=ip_address,
        )
        public_citation_sources = (
            [
                FinalizedCitationSource(
                    source_number=1, chunk=prompt_finalized_sources[0].chunk
                )
            ]
            if prompt_finalized_sources
            else []
        )
        if not public_citation_sources:
            raise

        fallback_answer = _build_extractive_fallback_answer(public_citation_sources[0])
        assistant_message = _create_chat_message_record(
            session_id=active_session_id,
            user_id=user_id,
            role="assistant",
            content=fallback_answer,
            model_used=EXTRACTIVE_FALLBACK_MODEL_NAME,
            settings=current_settings,
        )
        _store_message_citations(
            message_id=assistant_message["id"],
            sources=public_citation_sources,
        )
        record_audit_log_sync(
            action="chat_answer_created",
            user_id=user_id,
            resource_type="chat_message",
            resource_id=assistant_message["id"],
            metadata={
                "model_used": EXTRACTIVE_FALLBACK_MODEL_NAME,
                "citation_count": len(public_citation_sources),
                "context_chunk_count": len(prompt.used_chunks),
                "retrieval_passed": True,
                "llm_fallback_reason": exc.detail,
            },
            ip_address=ip_address,
        )

        assistant_message_record = ChatMessageRecord(
            message_id=assistant_message["id"],
            session_id=active_session_id,
            role="assistant",
            content=fallback_answer,
            model_used=EXTRACTIVE_FALLBACK_MODEL_NAME,
            prompt_tokens=None,
            completion_tokens=None,
            estimated_cost=None,
            created_at=assistant_message["created_at"],
            citations=[
                ChatMessageCitation(
                    source_number=source.source_number,
                    chunk_id=source.chunk.chunk_id,
                    document_id=source.chunk.document_id,
                    source_file=source.chunk.source_file,
                    page_number=source.chunk.page_number,
                    section_title=source.chunk.section_title,
                    similarity_score=source.chunk.combined_score,
                )
                for source in public_citation_sources
            ],
        )
        _publish_chat_session_snapshot(user_id, active_session_id)
        _publish_chat_message_created(
            user_id=user_id,
            session_id=active_session_id,
            message=assistant_message_record,
        )

        return ChatResponse(
            session_id=active_session_id,
            answer=fallback_answer,
            sources=[
                {
                    "source_number": source.source_number,
                    "chunk_id": source.chunk.chunk_id,
                    "document_id": source.chunk.document_id,
                    "source_file": source.chunk.source_file,
                    "page_number": source.chunk.page_number,
                    "section_title": source.chunk.section_title,
                    "subsection_title": source.chunk.subsection_title,
                    "chunk_index": source.chunk.chunk_index,
                    "score": source.chunk.combined_score,
                }
                for source in public_citation_sources
            ],
            model_used=EXTRACTIVE_FALLBACK_MODEL_NAME,
            retrieval_passed=True,
            user_message=user_message_record,
            assistant_message=assistant_message_record,
            debug=debug_payload,
        )

    record_audit_log_sync(
        action="llm_call_succeeded",
        user_id=user_id,
        resource_type="chat_session",
        resource_id=active_session_id,
        metadata={
            "message_id": str(user_message["id"]),
            "model_used": llm_response.model_used,
            "prompt_tokens": llm_response.usage.prompt_tokens,
            "completion_tokens": llm_response.usage.completion_tokens,
        },
        ip_address=ip_address,
    )
    if llm_response.fallback_used:
        record_audit_log_sync(
            action="model_fallback_used",
            user_id=user_id,
            resource_type="chat_session",
            resource_id=active_session_id,
            metadata={"model_used": llm_response.model_used},
            ip_address=ip_address,
        )

    candidate_answer = llm_response.answer
    answer_was_corrected = False
    is_nei = _is_not_enough_info_answer(candidate_answer)
    logger.info(
        "Path C: LLM responded (model=%s, is_not_enough_info=%s, answer_preview=%s)",
        llm_response.model_used,
        is_nei,
        candidate_answer[:120],
    )
    if not is_nei:
        candidate_answer, answer_was_corrected = _correct_answer_if_needed(
            question=cleaned_question,
            answer=candidate_answer,
            finalized_sources=prompt_finalized_sources,
            settings=current_settings,
        )
    elif retrieval_result.chunks:
        re_result = _attempt_re_retrieval(
            user_id=user_id,
            question=cleaned_question,
            document_ids=document_ids,
            session_id=active_session_id,
            message_id=user_message["id"],
            settings=current_settings,
        )
        if re_result is not None and re_result.chunks:
            re_sources = _finalize_public_sources(re_result.chunks)
            re_prompt = build_grounded_prompt(
                question=cleaned_question,
                retrieved_chunks=[s.chunk for s in re_sources],
                settings=current_settings,
            )
            try:
                re_response = generate_chat_completion(
                    re_prompt.messages, settings=current_settings
                )
                re_answer = re_response.answer
                if not _is_not_enough_info_answer(re_answer):
                    re_finalized = _build_prompt_finalized_sources(
                        finalized_sources=re_sources,
                        prompt_used_chunks=re_prompt.used_chunks,
                    )
                    re_answer, _ = _correct_answer_if_needed(
                        question=cleaned_question,
                        answer=re_answer,
                        finalized_sources=re_finalized,
                        settings=current_settings,
                    )
                    if not _is_not_enough_info_answer(re_answer):
                        candidate_answer = re_answer
                        finalized_prompt_sources = re_sources
                        prompt_finalized_sources = re_finalized
                        llm_response = re_response
                        answer_was_corrected = True
                        is_nei = False
            except DependencyUnavailableError:
                pass

    assistant_message = _create_chat_message_record(
        session_id=active_session_id,
        user_id=user_id,
        role="assistant",
        content=candidate_answer,
        model_used=llm_response.model_used,
        prompt_tokens=llm_response.usage.prompt_tokens,
        completion_tokens=llm_response.usage.completion_tokens,
        estimated_cost=None,
        settings=current_settings,
    )
    is_not_enough_info_answer = _is_not_enough_info_answer(candidate_answer)
    finalized_answer = (
        NOT_ENOUGH_INFO_MESSAGE if is_not_enough_info_answer else candidate_answer
    )
    public_citation_sources: list[FinalizedCitationSource] = []
    if is_not_enough_info_answer:
        if finalized_answer != candidate_answer:
            _update_chat_message_content(
                message_id=assistant_message["id"],
                content=finalized_answer,
                settings=current_settings,
            )
    else:
        finalized_answer, public_citation_sources = _apply_backend_citation_labels(
            answer=candidate_answer,
            finalized_sources=prompt_finalized_sources,
        )
        if finalized_answer != candidate_answer:
            _update_chat_message_content(
                message_id=assistant_message["id"],
                content=finalized_answer,
                settings=current_settings,
            )
    if public_citation_sources:
        _store_message_citations(
            message_id=assistant_message["id"],
            sources=public_citation_sources,
        )
    record_audit_log_sync(
        action="chat_answer_created",
        user_id=user_id,
        resource_type="chat_message",
        resource_id=assistant_message["id"],
        metadata={
            "model_used": llm_response.model_used,
            "citation_count": len(public_citation_sources),
            "context_chunk_count": len(prompt.used_chunks),
            "retrieval_passed": not is_not_enough_info_answer,
            "answer_corrected": answer_was_corrected,
        },
        ip_address=ip_address,
    )

    assistant_message_record = ChatMessageRecord(
        message_id=assistant_message["id"],
        session_id=active_session_id,
        role="assistant",
        content=finalized_answer,
        model_used=llm_response.model_used,
        prompt_tokens=llm_response.usage.prompt_tokens,
        completion_tokens=llm_response.usage.completion_tokens,
        estimated_cost=None,
        created_at=assistant_message["created_at"],
        citations=[
            ChatMessageCitation(
                source_number=source.source_number,
                chunk_id=source.chunk.chunk_id,
                document_id=source.chunk.document_id,
                source_file=source.chunk.source_file,
                page_number=source.chunk.page_number,
                section_title=source.chunk.section_title,
                similarity_score=source.chunk.combined_score,
            )
            for source in public_citation_sources
        ],
    )
    _publish_chat_session_snapshot(user_id, active_session_id)
    _publish_chat_message_created(
        user_id=user_id,
        session_id=active_session_id,
        message=assistant_message_record,
    )

    return ChatResponse(
        session_id=active_session_id,
        answer=finalized_answer,
        sources=[
            {
                "source_number": source.source_number,
                "chunk_id": source.chunk.chunk_id,
                "document_id": source.chunk.document_id,
                "source_file": source.chunk.source_file,
                "page_number": source.chunk.page_number,
                "section_title": source.chunk.section_title,
                "subsection_title": source.chunk.subsection_title,
                "chunk_index": source.chunk.chunk_index,
                "score": source.chunk.combined_score,
            }
            for source in public_citation_sources
        ],
        model_used=llm_response.model_used,
        retrieval_passed=not is_not_enough_info_answer,
        user_message=user_message_record,
        assistant_message=assistant_message_record,
        debug=debug_payload,
    )
