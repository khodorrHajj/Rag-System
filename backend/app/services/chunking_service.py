from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Iterable
from uuid import UUID

from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.schemas.ingestion import ChunkCandidate, ParsedDocumentUnit

WHITESPACE_RE = re.compile(r"[ \t]+")
PARAGRAPH_SPLIT_RE = re.compile(r"\n{2,}")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")

@dataclass(frozen=True)
class ChunkingConfig:
    max_chars: int
    overlap_chars: int
    min_chars: int
    hard_max_chars: int
    max_chunks_per_document: int
    enable_semantic_chunking: bool

def _build_chunking_config(settings: Settings | None = None) -> ChunkingConfig:
    current_settings = settings or get_settings()

    max_chars = max(current_settings.chunk_max_chars, 50)
    overlap_chars = max(
        min(current_settings.chunk_overlap_chars, max(max_chars - 1, 0)), 0
    )
    min_chars = max(min(current_settings.chunk_min_chars, max_chars), 1)
    hard_max_chars = max(current_settings.chunk_hard_max_chars, max_chars + 100)
    max_chunks_per_document = max(current_settings.max_chunks_per_document, 1)

    return ChunkingConfig(
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        min_chars=min_chars,
        hard_max_chars=hard_max_chars,
        max_chunks_per_document=max_chunks_per_document,
        enable_semantic_chunking=current_settings.enable_semantic_chunking,
    )
    min_chars = max(min(current_settings.chunk_min_chars, max_chars), 1)
    max_chunks_per_document = max(current_settings.max_chunks_per_document, 1)

    return ChunkingConfig(
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        min_chars=min_chars,
        max_chunks_per_document=max_chunks_per_document,
        enable_semantic_chunking=current_settings.enable_semantic_chunking,
    )

def clean_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = WHITESPACE_RE.sub(" ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)

    return normalized.strip()

def estimate_token_count(text: str) -> int:
    cleaned = clean_text(text)
    if not cleaned:
        return 0

    return max(1, round(len(cleaned) / 4))

def _trim_overlap_source(text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0 or len(text) <= overlap_chars:
        return text

    candidate = text[-overlap_chars:].strip()
    if not candidate:
        return ""

    for delimiter in ("\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "):
        index = candidate.find(delimiter)
        if index >= 0 and index + len(delimiter) < len(candidate):
            return candidate[index + len(delimiter) :].strip()

    return candidate

def _split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in PARAGRAPH_SPLIT_RE.split(text) if part.strip()]

def _split_sentences(text: str) -> list[str]:
    normalized = clean_text(text)
    if not normalized:
        return []

    sentences = [
        part.strip() for part in SENTENCE_SPLIT_RE.split(normalized) if part.strip()
    ]
    if len(sentences) <= 1:
        return [normalized]

    return sentences

def _split_words(text: str) -> list[str]:
    return [part for part in clean_text(text).split(" ") if part]

def _combine_parts(
    parts: Iterable[str],
    *,
    max_chars: int,
    overlap_chars: int,
    delimiter: str,
    next_level: int,
) -> list[str]:
    segments = [part.strip() for part in parts if part and part.strip()]
    if not segments:
        return []

    chunks: list[str] = []
    current = ""

    for segment in segments:
        candidate = segment if not current else f"{current}{delimiter}{segment}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current.strip())
            overlap = _trim_overlap_source(current, overlap_chars)
            candidate_with_overlap = (
                f"{overlap}{delimiter}{segment}".strip() if overlap else segment
            )
            if len(candidate_with_overlap) <= max_chars:
                current = candidate_with_overlap
                continue
        else:
            overlap = ""

        nested_chunks = _recursive_split_text(
            segment,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
            level=next_level,
        )
        if not nested_chunks:
            current = ""
            continue

        if overlap:
            first_candidate = f"{overlap}{delimiter}{nested_chunks[0]}".strip()
            if len(first_candidate) <= max_chars:
                nested_chunks[0] = first_candidate

        chunks.extend(nested_chunks[:-1])
        current = nested_chunks[-1]

    if current:
        chunks.append(current.strip())

    return [chunk for chunk in chunks if chunk]

def _semantic_group_sentences(
    text: str,
    *,
    max_chars: int,
) -> list[str]:
    sentences = _split_sentences(text)
    if len(sentences) <= 2:
        return [clean_text(text)] if clean_text(text) else []

    groups: list[str] = []
    current_group = sentences[0]
    previous_tokens = set(sentences[0].lower().split())

    for sentence in sentences[1:]:
        sentence_tokens = set(sentence.lower().split())
        shared = len(previous_tokens & sentence_tokens)
        total = len(previous_tokens | sentence_tokens) or 1
        similarity = shared / total
        proposed = f"{current_group} {sentence}".strip()

        if similarity < 0.08 and len(current_group) >= max_chars // 3:
            groups.append(current_group.strip())
            current_group = sentence
        elif len(proposed) <= max_chars:
            current_group = proposed
        else:
            groups.append(current_group.strip())
            current_group = sentence

        previous_tokens = sentence_tokens

    if current_group.strip():
        groups.append(current_group.strip())

    return groups

def recursive_split_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    return _recursive_split_text(
        text, max_chars=max_chars, overlap_chars=overlap_chars, level=0
    )

def _split_characters(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    cleaned = clean_text(text)
    if not cleaned:
        return []

    chunks: list[str] = []
    start = 0
    step = max(max_chars - overlap_chars, 1)
    while start < len(cleaned):
        end = min(start + max_chars, len(cleaned))
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start += step

    return chunks

def _recursive_split_text(
    text: str,
    *,
    max_chars: int,
    overlap_chars: int,
    level: int,
) -> list[str]:
    cleaned = clean_text(text)
    if not cleaned:
        return []

    if len(cleaned) <= max_chars:
        return [cleaned]

    splitters: list[tuple[Callable[[str], list[str]], str]] = [
        (_split_paragraphs, "\n\n"),
        (_split_sentences, " "),
        (_split_words, " "),
    ]

    if level >= len(splitters):
        return _split_characters(cleaned, max_chars, overlap_chars)

    splitter, delimiter = splitters[level]
    parts = splitter(cleaned)
    if len(parts) <= 1:
        return _recursive_split_text(
            cleaned,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
            level=level + 1,
        )

    return _combine_parts(
        parts,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        delimiter=delimiter,
        next_level=level + 1,
    )

def _merge_tiny_chunks(chunks: list[str], min_chars: int, max_chars: int) -> list[str]:
    if not chunks:
        return []

    merged: list[str] = []
    pending = ""

    for chunk in chunks:
        if not pending:
            pending = chunk
            continue

        if len(pending) < min_chars and len(f"{pending}\n\n{chunk}") <= max_chars:
            pending = f"{pending}\n\n{chunk}".strip()
            continue

        merged.append(pending.strip())
        pending = chunk

    if pending:
        if (
            merged
            and len(pending) < min_chars
            and len(f"{merged[-1]}\n\n{pending}") <= max_chars
        ):
            merged[-1] = f"{merged[-1]}\n\n{pending}".strip()
        else:
            merged.append(pending.strip())

    return [chunk for chunk in merged if chunk]

def _enforce_hard_max_chars(
    chunks: list[str], hard_max_chars: int, overlap_chars: int
) -> list[str]:
    result: list[str] = []
    for chunk in chunks:
        if len(chunk) <= hard_max_chars:
            result.append(chunk)
        else:
            result.extend(recursive_split_text(chunk, hard_max_chars, overlap_chars))
    return result

def _expand_unit_texts(
    unit: ParsedDocumentUnit,
    chunking_config: ChunkingConfig,
) -> list[str]:
    cleaned = clean_text(unit.text)
    if not cleaned:
        return []

    if len(cleaned) <= chunking_config.max_chars:
        return [cleaned]

    if chunking_config.enable_semantic_chunking:
        semantic_groups = _semantic_group_sentences(
            cleaned,
            max_chars=chunking_config.max_chars,
        )
        if semantic_groups and semantic_groups != [cleaned]:
            semantic_chunks: list[str] = []
            for group in semantic_groups:
                if len(group) <= chunking_config.max_chars:
                    semantic_chunks.append(group)
                else:
                    semantic_chunks.extend(
                        recursive_split_text(
                            group,
                            chunking_config.max_chars,
                            chunking_config.overlap_chars,
                        )
                    )
            merged = _merge_tiny_chunks(
                semantic_chunks,
                chunking_config.min_chars,
                chunking_config.max_chars,
            )
            return _enforce_hard_max_chars(
                merged, chunking_config.hard_max_chars, chunking_config.overlap_chars
            )

    merged = _merge_tiny_chunks(
        recursive_split_text(
            cleaned,
            chunking_config.max_chars,
            chunking_config.overlap_chars,
        ),
        chunking_config.min_chars,
        chunking_config.max_chars,
    )
    return _enforce_hard_max_chars(
        merged, chunking_config.hard_max_chars, chunking_config.overlap_chars
    )

def chunk_parsed_document(
    parsed_units: list[ParsedDocumentUnit],
    document_id: UUID,
    user_id: UUID,
    config: Settings | None = None,
) -> list[ChunkCandidate]:
    chunking_config = _build_chunking_config(config)
    chunks: list[ChunkCandidate] = []

    for unit_index, unit in enumerate(parsed_units):
        unit_chunks = _expand_unit_texts(unit, chunking_config)
        for content in unit_chunks:
            if len(chunks) >= chunking_config.max_chunks_per_document:
                raise AppError(
                    "Document produced too many chunks for the current processing limits.",
                    status_code=400,
                )

            chunk = ChunkCandidate(
                document_id=document_id,
                user_id=user_id,
                chunk_index=len(chunks),
                content=content,
                page_number=unit.page_number,
                section_title=unit.section_title,
                subsection_title=unit.subsection_title,
                token_count=estimate_token_count(content),
                metadata={
                    "chunking_strategy": (
                        "structure_semantic_recursive"
                        if chunking_config.enable_semantic_chunking
                        else "structure_recursive"
                    ),
                    "source_unit_index": unit_index,
                    "overlap_chars": chunking_config.overlap_chars,
                    **unit.metadata,
                },
            )
            chunks.append(chunk)

    if not chunks:
        raise AppError("Document did not produce any chunkable text.", status_code=400)

    return chunks
