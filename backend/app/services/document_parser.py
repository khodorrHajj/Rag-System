from __future__ import annotations

from io import BytesIO
import re
from statistics import median
from typing import Any

from docx import Document as DocxDocument

from app.config import Settings, get_settings
from app.core.exceptions import AppError, RequestEntityTooLargeError
from app.schemas.ingestion import ParsedDocumentUnit

MAX_TXT_NULL_RATIO = 0.05
PDF_WORD_Y_TOLERANCE = 3.0
PDF_MULTI_COLUMN_MIN_LINE_SPLITS = 6
PDF_COLUMN_GAP_MIN = 24.0
PDF_HEADING_FONT_DELTA = 4.0
PDF_SUBHEADING_FONT_DELTA = 1.5
PDF_HEADING_ZONE_RATIO = 0.35
PDF_CROP_MARGIN = 4.0
PDF_SUBSECTION_SCAN_LIMIT = 180.0

def _normalize_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r" {2,}", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)

    return normalized.strip()

def _safe_txt_decode(file_bytes: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue

    return file_bytes.decode("utf-8", errors="replace")


def _group_pdf_words_into_lines(
    words: list[dict[str, Any]],
    *,
    y_tolerance: float = PDF_WORD_Y_TOLERANCE,
) -> list[list[dict[str, Any]]]:
    lines: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda value: (float(value["top"]), float(value["x0"]))):
        if not lines:
            lines.append([word])
            continue

        if abs(float(word["top"]) - float(lines[-1][0]["top"])) <= y_tolerance:
            lines[-1].append(word)
        else:
            lines.append([word])

    return lines


def _pdf_line_text(words: list[dict[str, Any]]) -> str:
    ordered_words = sorted(words, key=lambda value: float(value["x0"]))
    return clean_line_text(" ".join(str(word["text"]) for word in ordered_words))


def clean_line_text(value: str) -> str:
    return re.sub(r"\s{2,}", " ", value).strip()


def _percentile(values: list[float], proportion: float) -> float:
    if not values:
        raise ValueError("Cannot compute a percentile from an empty list.")

    clamped = max(0.0, min(proportion, 1.0))
    index = int((len(values) - 1) * clamped)
    return values[index]


def _detect_pdf_column_split(page: Any) -> float | None:
    words = page.extract_words(extra_attrs=["size"])
    if not words:
        return None

    body_font_size = median(float(word["size"]) for word in words)
    candidate_midpoints: list[float] = []

    for line in _group_pdf_words_into_lines(words):
        body_words = [
            word
            for word in line
            if float(word["size"]) <= body_font_size + 0.75
        ]
        if len(body_words) < 4:
            continue

        body_words = sorted(body_words, key=lambda value: float(value["x0"]))
        split_candidates: list[tuple[float, float]] = []
        for left_word, right_word in zip(body_words, body_words[1:]):
            gap = float(right_word["x0"]) - float(left_word["x1"])
            if gap < PDF_COLUMN_GAP_MIN:
                continue
            split_candidates.append(
                (gap, (float(left_word["x1"]) + float(right_word["x0"])) / 2.0)
            )

        if split_candidates:
            _, midpoint = max(split_candidates, key=lambda item: item[0])
            candidate_midpoints.append(midpoint)

    midpoint: float | None = None
    if len(candidate_midpoints) >= PDF_MULTI_COLUMN_MIN_LINE_SPLITS:
        candidate_midpoints.sort()
        midpoint = candidate_midpoints[len(candidate_midpoints) // 2]
        if midpoint <= page.width * 0.2 or midpoint >= page.width * 0.8:
            midpoint = None

    if midpoint is not None:
        return midpoint

    body_words = [
        word for word in words if float(word["size"]) <= body_font_size + 0.75
    ]
    if len(body_words) < 80:
        return None

    page_midpoint = float(page.width) / 2.0
    left_word_count = sum(
        1 for word in body_words if float(word["x1"]) <= page_midpoint - 12
    )
    right_word_count = sum(
        1 for word in body_words if float(word["x0"]) >= page_midpoint + 12
    )
    crossing_word_count = len(body_words) - left_word_count - right_word_count
    if (
        left_word_count >= 40
        and right_word_count >= 40
        and crossing_word_count <= len(body_words) * 0.25
    ):
        left_column_words = sorted(
            float(word["x1"])
            for word in body_words
            if (float(word["x0"]) + float(word["x1"])) / 2.0 <= page_midpoint
        )
        right_column_words = sorted(
            float(word["x0"])
            for word in body_words
            if (float(word["x0"]) + float(word["x1"])) / 2.0 > page_midpoint
        )
        if left_column_words and right_column_words:
            left_boundary = _percentile(left_column_words, 0.95)
            right_boundary = _percentile(right_column_words, 0.05)
            if right_boundary - left_boundary >= 12:
                return (left_boundary + right_boundary) / 2.0
        return page_midpoint

    return None


def _extract_pdf_section_title(
    words: list[dict[str, Any]],
    *,
    body_font_size: float,
    page_height: float,
) -> tuple[str | None, float]:
    heading_lines: list[str] = []
    heading_bottom = 0.0

    for line in _group_pdf_words_into_lines(words):
        line_top = float(line[0]["top"])
        if line_top > page_height * PDF_HEADING_ZONE_RATIO:
            break
        if heading_bottom and line_top > heading_bottom + 8:
            break

        line_max_font_size = max(float(word["size"]) for word in line)
        if line_max_font_size > body_font_size + PDF_HEADING_FONT_DELTA:
            heading_lines.append(_pdf_line_text(line))
            heading_bottom = max(
                heading_bottom,
                max(float(word["bottom"]) for word in line),
            )
            continue

    if not heading_lines:
        return None, 0.0

    return _normalize_text("\n".join(heading_lines)), heading_bottom


def _extract_pdf_subsection_title(
    words: list[dict[str, Any]],
    *,
    body_font_size: float,
    section_bottom: float,
    column_split: float | None,
) -> str | None:
    left_region_words = [
        word
        for word in words
        if column_split is None
        or float(word["x0"]) < column_split - PDF_CROP_MARGIN
    ]
    if not left_region_words:
        return None

    subsection_lines: list[str] = []
    started = False
    scan_limit = section_bottom + PDF_SUBSECTION_SCAN_LIMIT

    for line in _group_pdf_words_into_lines(left_region_words):
        line_top = float(line[0]["top"])
        if line_top <= section_bottom + 4:
            continue
        if line_top > scan_limit:
            break

        line_max_font_size = max(float(word["size"]) for word in line)
        if line_max_font_size > body_font_size + PDF_SUBHEADING_FONT_DELTA:
            subsection_lines.append(_pdf_line_text(line))
            started = True
            continue

        if started:
            break

    if not subsection_lines:
        return None

    return _normalize_text("\n".join(subsection_lines))


def _extract_pdf_page_text(
    page: Any,
) -> tuple[str, str | None, str | None, dict[str, Any]]:
    words = page.extract_words(extra_attrs=["fontname", "size"])
    if not words:
        return "", None, None, {"column_layout": "empty"}

    body_font_size = median(float(word["size"]) for word in words)
    column_split = _detect_pdf_column_split(page)
    section_title, section_bottom = _extract_pdf_section_title(
        words,
        body_font_size=body_font_size,
        page_height=float(page.height),
    )
    subsection_title = _extract_pdf_subsection_title(
        words,
        body_font_size=body_font_size,
        section_bottom=section_bottom,
        column_split=column_split,
    )

    if column_split is None:
        raw_text = page.extract_text_simple() or page.extract_text(layout=False) or ""
        return (
            _normalize_text(raw_text),
            section_title,
            subsection_title,
            {"column_layout": "single"},
        )

    heading_top = section_bottom + PDF_CROP_MARGIN if section_bottom else 0.0
    top_text = ""
    if section_bottom:
        top_text = (
            page.crop((0, 0, page.width, heading_top)).extract_text_simple() or ""
        )
    left_text = (
        page.crop((0, heading_top, max(column_split - PDF_CROP_MARGIN, 0), page.height))
        .extract_text_simple()
        or ""
    )
    right_text = (
        page.crop(
            (
                min(column_split + PDF_CROP_MARGIN, page.width),
                heading_top,
                page.width,
                page.height,
            )
        ).extract_text_simple()
        or ""
    )

    combined_text = "\n\n".join(
        part.strip() for part in (top_text, left_text, right_text) if part.strip()
    )
    return (
        _normalize_text(combined_text),
        section_title,
        subsection_title,
        {"column_layout": "multi", "column_split_x": round(column_split, 3)},
    )

def _infer_txt_section_title(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    first_line = lines[0]
    if len(first_line) > 120:
        return None

    if len(lines) > 1:
        return first_line

    return None

def _detect_docx_heading_level(style_name: str) -> int | None:
    match = re.match(r"Heading\s+(\d+)", style_name.strip(), flags=re.IGNORECASE)
    if match:
        return int(match.group(1))

    if style_name.strip().lower() == "title":
        return 1

    return None

def validate_stored_document_for_parsing(
    document_row: dict[str, Any],
    file_bytes: bytes,
    settings: Settings | None = None,
) -> None:
    current_settings = settings or get_settings()
    file_type = str(document_row["file_type"]).lower()
    storage_path = str(document_row["storage_path"])
    file_size_bytes = int(document_row["file_size_bytes"])

    if file_type == "doc":
        raise AppError(
            "Legacy .doc files are not supported. Please upload .docx, .pdf, or .txt.",
            status_code=400,
        )

    if file_type not in current_settings.allowed_upload_extensions:
        raise AppError("Unsupported file type for parsing.", status_code=400)

    if not storage_path.lower().endswith(f".{file_type}"):
        raise AppError(
            "Stored file metadata does not match its extension.", status_code=400
        )

    if file_size_bytes <= 0 or len(file_bytes) <= 0:
        raise AppError("Document file is empty.", status_code=400)

    if (
        file_size_bytes > current_settings.max_upload_size_bytes
        or len(file_bytes) > current_settings.max_upload_size_bytes
    ):
        raise RequestEntityTooLargeError(
            f"Uploaded file exceeds the maximum allowed size of {current_settings.max_upload_size_mb} MB."
        )

    if len(file_bytes) != file_size_bytes:
        raise AppError("Stored file size does not match metadata.", status_code=400)

    if file_type == "pdf" and not file_bytes.startswith(b"%PDF"):
        raise AppError("Stored PDF file is invalid or corrupted.", status_code=400)

    if file_type == "docx" and not file_bytes.startswith(
        (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
    ):
        raise AppError("Stored DOCX file is invalid or corrupted.", status_code=400)

    if file_type == "txt":
        null_ratio = file_bytes.count(b"\x00") / max(len(file_bytes), 1)
        if null_ratio > MAX_TXT_NULL_RATIO:
            raise AppError(
                "Stored text file appears to be binary data.", status_code=400
            )

def _parse_pdf(file_bytes: bytes) -> tuple[str, list[ParsedDocumentUnit]]:
    import pdfplumber

    try:
        pdf = pdfplumber.open(BytesIO(file_bytes))
    except Exception as exc:
        raise AppError(
            "PDF parsing failed. The file may be invalid or unsupported.",
            status_code=400,
        ) from exc

    units: list[ParsedDocumentUnit] = []
    saw_multi_column_page = False
    for page in pdf.pages:
        page_text, section_title, subsection_title, metadata = _extract_pdf_page_text(
            page
        )
        if not page_text:
            continue
        if metadata.get("column_layout") == "multi":
            saw_multi_column_page = True

        content_type = "narrative"
        normalized_section_title = (section_title or "").strip().lower()
        if normalized_section_title in {"contents", "table of contents"}:
            content_type = "table_of_contents"

        units.append(
            ParsedDocumentUnit(
                text=page_text,
                page_number=page.page_number,
                section_title=section_title,
                subsection_title=subsection_title,
                metadata={
                    "file_type": "pdf",
                    "parser": (
                        "pdfplumber-column-aware"
                        if metadata.get("column_layout") == "multi"
                        else "pdfplumber"
                    ),
                    "content_type": content_type,
                    **metadata,
                },
            )
        )

    pdf.close()

    return (
        "pdfplumber-column-aware" if saw_multi_column_page else "pdfplumber",
        units,
    )

def _parse_txt(file_bytes: bytes) -> tuple[str, list[ParsedDocumentUnit]]:
    text = _normalize_text(_safe_txt_decode(file_bytes))
    if not text:
        return "text", []

    return (
        "text",
        [
            ParsedDocumentUnit(
                text=text,
                page_number=None,
                section_title=_infer_txt_section_title(text),
                subsection_title=None,
                metadata={"file_type": "txt", "parser": "text"},
            )
        ],
    )

def _parse_docx(file_bytes: bytes) -> tuple[str, list[ParsedDocumentUnit]]:
    try:
        document = DocxDocument(BytesIO(file_bytes))
    except Exception as exc:
        raise AppError(
            "DOCX parsing failed. The file may be invalid or unsupported.",
            status_code=400,
        ) from exc

    units: list[ParsedDocumentUnit] = []
    current_section_title: str | None = None
    current_subsection_title: str | None = None

    for paragraph in document.paragraphs:
        paragraph_text = _normalize_text(paragraph.text)
        if not paragraph_text:
            continue

        style_name = paragraph.style.name if paragraph.style is not None else ""
        heading_level = _detect_docx_heading_level(style_name)

        if heading_level == 1:
            current_section_title = paragraph_text
            current_subsection_title = None
        elif heading_level and heading_level >= 2:
            current_subsection_title = paragraph_text

        units.append(
            ParsedDocumentUnit(
                text=paragraph_text,
                page_number=None,
                section_title=current_section_title,
                subsection_title=current_subsection_title,
                metadata={
                    "file_type": "docx",
                    "parser": "python-docx",
                    "style_name": style_name,
                    "heading_level": heading_level,
                },
            )
        )

    return "python-docx", units

def parse_document_bytes(
    document_row: dict[str, Any],
    file_bytes: bytes,
    settings: Settings | None = None,
) -> tuple[str, list[ParsedDocumentUnit]]:
    validate_stored_document_for_parsing(document_row, file_bytes, settings=settings)
    file_type = str(document_row["file_type"]).lower()

    if file_type == "pdf":
        parser_name, units = _parse_pdf(file_bytes)
    elif file_type == "txt":
        parser_name, units = _parse_txt(file_bytes)
    elif file_type == "docx":
        parser_name, units = _parse_docx(file_bytes)
    elif file_type == "doc":
        raise AppError(
            "Legacy .doc files are not supported. Please upload .docx, .pdf, or .txt.",
            status_code=400,
        )
    else:
        raise AppError("Unsupported file type for parsing.", status_code=400)

    if not units:
        raise AppError("Document did not contain extractable text.", status_code=400)

    return parser_name, units
