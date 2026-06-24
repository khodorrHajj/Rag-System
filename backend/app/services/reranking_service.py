from __future__ import annotations

import re

from app.schemas.retrieval import RetrievedChunk

TOKEN_RE = re.compile(r"[a-z0-9]+")
TABLE_OF_CONTENTS_LINE_RE = re.compile(
    r"(?m)^\s*(?:\d+(?:\.\d+)*)?[\sA-Za-z,\-()]+?\s+\d{1,3}\s*$"
)
COMPARISON_TERMS = {
    "greatest",
    "highest",
    "lowest",
    "largest",
    "smallest",
    "increase",
    "decrease",
    "before",
    "after",
    "between",
    "same",
    "which",
}
RERANK_STOPWORDS = {
    "a",
    "about",
    "according",
    "an",
    "and",
    "at",
    "by",
    "did",
    "do",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "of",
    "on",
    "the",
    "their",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
}

def _tokenize(value: str) -> set[str]:
    return {token for token in TOKEN_RE.findall(value.lower()) if token}


def _tokenize_without_stopwords(value: str) -> set[str]:
    return {
        token for token in TOKEN_RE.findall(value.lower()) if token not in RERANK_STOPWORDS
    }

def _exact_phrase_boost(query: str, candidate: RetrievedChunk) -> float:
    query_lower = query.lower().strip()
    if not query_lower:
        return 0.0

    haystacks = [
        candidate.content.lower(),
        (candidate.section_title or "").lower(),
        (candidate.subsection_title or "").lower(),
        candidate.source_file.lower(),
    ]
    if any(query_lower in haystack for haystack in haystacks):
        return 0.12

    return 0.0

def _section_match_boost(query_tokens: set[str], candidate: RetrievedChunk) -> float:
    if not query_tokens:
        return 0.0

    section_tokens = _tokenize(
        " ".join(filter(None, [candidate.section_title, candidate.subsection_title]))
    )
    if not section_tokens:
        return 0.0

    overlap_ratio = len(query_tokens & section_tokens) / len(query_tokens)
    if overlap_ratio >= 0.75:
        return 0.08
    if overlap_ratio >= 0.4:
        return 0.04

    return 0.0

def _filename_boost(query_tokens: set[str], candidate: RetrievedChunk) -> float:
    if not query_tokens:
        return 0.0

    filename_tokens = _tokenize(candidate.source_file)
    if not filename_tokens:
        return 0.0

    overlap_ratio = len(query_tokens & filename_tokens) / len(query_tokens)
    if overlap_ratio >= 0.5:
        return 0.05
    if overlap_ratio > 0:
        return 0.02

    return 0.0

def _focus_boost(candidate: RetrievedChunk) -> float:
    token_count = candidate.token_count or 0
    if 40 <= token_count <= 220:
        return 0.03
    if 221 <= token_count <= 320:
        return 0.015

    return 0.0

def _numeric_overlap_boost(query: str, candidate: RetrievedChunk) -> float:
    query_numbers = set(re.findall(r"\b\d{1,4}\b", query))
    if not query_numbers:
        return 0.0

    candidate_numbers = set(re.findall(r"\b\d{1,4}\b", candidate.content))
    overlap = len(query_numbers & candidate_numbers)
    if overlap >= 2:
        return 0.08
    if overlap == 1:
        return 0.035

    return 0.0

def _comparison_boost(query_tokens: set[str], candidate: RetrievedChunk) -> float:
    if not query_tokens:
        return 0.0

    content_tokens = _tokenize(
        " ".join(
            filter(
                None,
                [
                    candidate.section_title,
                    candidate.subsection_title,
                    candidate.content[:1200],
                ],
            )
        )
    )
    comparison_overlap = len(query_tokens & COMPARISON_TERMS & content_tokens)

    if comparison_overlap >= 2:
        return 0.06
    if comparison_overlap == 1:
        return 0.025

    return 0.0


def _section_reference_boost(
    section_reference: str | None,
    candidate: RetrievedChunk,
) -> float:
    if not section_reference:
        return 0.0

    normalized_reference = " ".join(section_reference.lower().split())
    if not normalized_reference:
        return 0.0

    section_title = " ".join((candidate.section_title or "").lower().split())
    subsection_title = " ".join((candidate.subsection_title or "").lower().split())
    content_start = " ".join(candidate.content[:240].lower().split())

    if normalized_reference == section_title or normalized_reference == subsection_title:
        return 0.2
    if section_title.startswith(normalized_reference) or subsection_title.startswith(
        normalized_reference
    ):
        return 0.14
    if normalized_reference in content_start:
        return 0.09
    if normalized_reference in candidate.content.lower():
        return 0.04

    return 0.0


def _is_probable_table_of_contents(candidate: RetrievedChunk) -> bool:
    content_type = str(candidate.metadata.get("content_type") or "").lower()
    if content_type == "table_of_contents":
        return True

    normalized_section_title = " ".join((candidate.section_title or "").lower().split())
    if normalized_section_title in {"contents", "table of contents"}:
        return True

    if candidate.chunk_index > 15:
        return False

    toc_line_count = len(TABLE_OF_CONTENTS_LINE_RE.findall(candidate.content[:1600]))
    return toc_line_count >= 3


def _query_targets_section_content(
    query: str,
    section_reference: str | None,
) -> bool:
    normalized_query = " ".join(query.lower().split())
    if section_reference:
        normalized_query = normalized_query.replace(
            " ".join(section_reference.lower().split()),
            " ",
            1,
        )

    remaining_tokens = _tokenize_without_stopwords(normalized_query)
    if len(remaining_tokens) >= 4:
        return True

    return bool(re.search(r"\b\d{4}\b", query))


def _table_of_contents_penalty(
    query: str,
    section_reference: str | None,
    candidate: RetrievedChunk,
) -> float:
    if not _is_probable_table_of_contents(candidate):
        return 0.0
    if not _query_targets_section_content(query, section_reference):
        return 0.0

    return 0.24


def _chunk_diversity_key(
    candidate: RetrievedChunk,
) -> tuple[str, int | None, str, str, str]:
    normalized_content = " ".join(candidate.content.lower().split())
    return (
        candidate.source_file.lower(),
        candidate.page_number,
        " ".join((candidate.section_title or "").lower().split()),
        " ".join((candidate.subsection_title or "").lower().split()),
        normalized_content[:420],
    )

def rerank_chunks(
    query: str,
    candidates: list[RetrievedChunk],
    top_k: int,
    *,
    section_reference: str | None = None,
) -> list[RetrievedChunk]:
    query_tokens = _tokenize(query)
    reranked: list[RetrievedChunk] = []

    for candidate in candidates:
        boost = (
            _exact_phrase_boost(query, candidate)
            + _section_match_boost(query_tokens, candidate)
            + _filename_boost(query_tokens, candidate)
            + _focus_boost(candidate)
            + _numeric_overlap_boost(query, candidate)
            + _comparison_boost(query_tokens, candidate)
            + _section_reference_boost(section_reference, candidate)
        )
        penalty = _table_of_contents_penalty(query, section_reference, candidate)
        reranked.append(
            candidate.model_copy(
                update={
                    "combined_score": round(
                        max(min(candidate.combined_score + boost - penalty, 1.0), 0.0),
                        6,
                    )
                }
            )
        )

    reranked.sort(
        key=lambda chunk: (
            chunk.combined_score,
            chunk.vector_score or 0.0,
            chunk.keyword_score or 0.0,
            -(chunk.token_count or 0),
        ),
        reverse=True,
    )

    deduplicated: list[RetrievedChunk] = []
    seen_diversity_keys: set[tuple[str, int | None, str, str, str]] = set()
    for chunk in reranked:
        diversity_key = _chunk_diversity_key(chunk)
        if diversity_key in seen_diversity_keys:
            continue
        seen_diversity_keys.add(diversity_key)
        deduplicated.append(chunk)
        if len(deduplicated) >= max(top_k, 1):
            break

    return deduplicated
