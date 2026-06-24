from __future__ import annotations

import json
import logging
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from app.config import BACKEND_DIR, REPOSITORY_DIR, Settings, get_settings
from app.core.database import database_connection
from app.core.exceptions import AppError, DependencyUnavailableError, NotFoundError
from app.schemas.evaluation import (
    EvaluationCase,
    EvaluationCaseFile,
    EvaluationExecutionPayload,
    EvaluationResultRecord,
    EvaluationRunResponse,
)
from app.services.llm_service import generate_chat_completion
from app.services.prompt_builder import build_grounded_prompt
from app.services.retrieval_service import retrieve_relevant_chunks

logger = logging.getLogger(__name__)

def _run_db_operation(operation_name: str, callback):
    try:
        return callback()
    except AppError:
        raise
    except psycopg.Error as exc:
        logger.exception("Database operation failed during %s", operation_name)
        raise DependencyUnavailableError("Database service is temporarily unavailable.") from exc

def _truncate_preview(text: str | None, max_chars: int) -> str | None:
    if not text:
        return None

    if len(text) <= max_chars:
        return text

    return f"{text[:max_chars].rstrip()}..."

def _resolve_eval_dir(settings: Settings) -> Path:
    raw_path = Path(settings.eval_cases_dir)
    if raw_path.is_absolute():
        return raw_path

    candidates = [
        REPOSITORY_DIR / raw_path,
        BACKEND_DIR / raw_path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[0]

def load_local_evaluation_cases(
    settings: Settings | None = None,
) -> list[EvaluationCaseFile]:
    current_settings = settings or get_settings()
    eval_dir = _resolve_eval_dir(current_settings)
    if not eval_dir.exists():
        return []

    case_files: list[EvaluationCaseFile] = []
    for path in sorted(eval_dir.glob("*.json")):
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw_payload, list):
            cases = [EvaluationCase.model_validate(item) for item in raw_payload]
        else:
            cases = [EvaluationCase.model_validate(raw_payload)]
        case_files.append(EvaluationCaseFile(file_name=path.name, cases=cases))

    return case_files

def _select_cases(
    *,
    run_all: bool,
    case_name: str | None,
    inline_case: EvaluationCase | None,
    settings: Settings,
) -> tuple[str, list[EvaluationCase]]:
    if inline_case is not None:
        return "single", [inline_case]

    local_case_files = load_local_evaluation_cases(settings)
    local_cases = [case for case_file in local_case_files for case in case_file.cases]

    if case_name:
        matching_cases = [case for case in local_cases if case.case_name == case_name]
        if not matching_cases:
            raise NotFoundError("Evaluation case not found.")
        return "named", matching_cases

    if not run_all:
        raise AppError("Provide an evaluation case or enable run_all.", status_code=400)

    if not local_cases:
        raise NotFoundError("No local evaluation cases were found.")

    return "all", local_cases

def _run_case(
    *,
    user_id: UUID,
    case: EvaluationCase,
    settings: Settings,
) -> EvaluationExecutionPayload:
    started_at = perf_counter()
    retrieval_result = retrieve_relevant_chunks(
        user_id=user_id,
        query=case.question,
        document_ids=case.document_ids,
        top_k=None,
        candidate_k=None,
        threshold=None,
        settings=settings,
    )

    answer_text: str | None = None
    citations_present = bool(retrieval_result.chunks)
    answer_generated = False

    if retrieval_result.retrieval_passed and retrieval_result.chunks:
        prompt = build_grounded_prompt(
            question=case.question,
            retrieved_chunks=retrieval_result.chunks,
            settings=settings,
        )
        try:
            llm_response = generate_chat_completion(prompt.messages, settings=settings)
            answer_text = llm_response.answer
            answer_generated = True
        except DependencyUnavailableError:
            logger.warning(
                "Skipping answer generation during evaluation because the LLM service is unavailable."
            )

    expected_terms_found = {
        term: bool(answer_text and term.lower() in answer_text.lower())
        for term in case.expected_answer_contains
    }
    expected_terms_passed = all(expected_terms_found.values()) if expected_terms_found else True

    retrieved_source_match = True
    if case.expected_source_file:
        retrieved_source_match = any(
            chunk.source_file == case.expected_source_file
            and (
                case.expected_page_number is None
                or chunk.page_number == case.expected_page_number
            )
            for chunk in retrieval_result.chunks
        )

    latency_ms = round((perf_counter() - started_at) * 1000)
    return EvaluationExecutionPayload(
        retrieval_passed=retrieval_result.retrieval_passed,
        retrieved_source_match=retrieved_source_match,
        expected_terms_found=expected_terms_found,
        expected_terms_passed=expected_terms_passed,
        answer_generated=answer_generated,
        citations_present=citations_present,
        latency_ms=latency_ms,
        answer_preview=_truncate_preview(answer_text, settings.eval_answer_preview_chars),
        retrieval_debug=retrieval_result.debug.model_dump(mode="json"),
    )

def run_evaluations(
    *,
    user_id: UUID,
    run_all: bool = True,
    case_name: str | None = None,
    case: EvaluationCase | None = None,
    settings: Settings | None = None,
) -> EvaluationRunResponse:
    current_settings = settings or get_settings()
    run_mode, selected_cases = _select_cases(
        run_all=run_all,
        case_name=case_name,
        inline_case=case,
        settings=current_settings,
    )

    run_id = uuid4()
    created_at = None
    results_payload: list[tuple[EvaluationCase, EvaluationExecutionPayload]] = []
    for evaluation_case in selected_cases:
        results_payload.append(
            (
                evaluation_case,
                _run_case(user_id=user_id, case=evaluation_case, settings=current_settings),
            )
        )

    def callback() -> tuple[dict[str, Any], list[dict[str, Any]]]:
        with database_connection(current_settings) as connection:
            with connection.cursor() as cursor:
                passed_count = sum(
                    1
                    for _, payload in results_payload
                    if payload.retrieval_passed
                    and payload.retrieved_source_match
                    and payload.expected_terms_passed
                    and payload.answer_generated
                    and payload.citations_present
                )
                cursor.execute(
                    """
                    INSERT INTO public.evaluation_runs (
                        id,
                        triggered_by_user_id,
                        run_mode,
                        case_count,
                        passed_count
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (run_id, user_id, run_mode, len(results_payload), passed_count),
                )
                run_row = cursor.fetchone()

                inserted_rows: list[dict[str, Any]] = []
                for evaluation_case, payload in results_payload:
                    cursor.execute(
                        """
                        INSERT INTO public.evaluation_results (
                            id,
                            run_id,
                            case_name,
                            question,
                            document_ids,
                            expected_answer_contains,
                            expected_source_file,
                            expected_page_number,
                            retrieval_passed,
                            retrieved_source_match,
                            expected_terms_found,
                            expected_terms_passed,
                            answer_generated,
                            citations_present,
                            latency_ms,
                            answer_preview
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING *
                        """,
                        (
                            uuid4(),
                            run_id,
                            evaluation_case.case_name,
                            evaluation_case.question,
                            Jsonb([str(document_id) for document_id in evaluation_case.document_ids or []]),
                            Jsonb(evaluation_case.expected_answer_contains),
                            evaluation_case.expected_source_file,
                            evaluation_case.expected_page_number,
                            payload.retrieval_passed,
                            payload.retrieved_source_match,
                            Jsonb(payload.expected_terms_found),
                            payload.expected_terms_passed,
                            payload.answer_generated,
                            payload.citations_present,
                            payload.latency_ms,
                            payload.answer_preview,
                        ),
                    )
                    inserted_rows.append(cursor.fetchone())
            connection.commit()

        return run_row, inserted_rows

    run_row, result_rows = _run_db_operation("run_evaluations", callback)
    created_at = run_row["created_at"]

    return EvaluationRunResponse(
        run_id=run_row["id"],
        run_mode=run_row["run_mode"],
        case_count=run_row["case_count"],
        passed_count=run_row["passed_count"],
        created_at=created_at,
        results=[
            EvaluationResultRecord(
                result_id=row["id"],
                run_id=row["run_id"],
                case_name=row.get("case_name"),
                question=row["question"],
                document_ids=[UUID(value) for value in row.get("document_ids", [])],
                retrieval_passed=row["retrieval_passed"],
                retrieved_source_match=row["retrieved_source_match"],
                expected_terms_found=row.get("expected_terms_found", {}),
                expected_terms_passed=row["expected_terms_passed"],
                answer_generated=row["answer_generated"],
                citations_present=row["citations_present"],
                latency_ms=row["latency_ms"],
                expected_source_file=row.get("expected_source_file"),
                expected_page_number=row.get("expected_page_number"),
                answer_preview=row.get("answer_preview"),
                created_at=row["created_at"],
            )
            for row in result_rows
        ],
    )

def list_evaluation_runs(
    settings: Settings | None = None,
) -> list[EvaluationRunResponse]:
    current_settings = settings or get_settings()

    def callback() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        with database_connection(current_settings) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM public.evaluation_runs
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (current_settings.eval_results_limit,),
                )
                run_rows = cursor.fetchall()
                run_ids = [row["id"] for row in run_rows]
                cursor.execute(
                    """
                    SELECT *
                    FROM public.evaluation_results
                    WHERE run_id = ANY(%s)
                    ORDER BY created_at DESC, id DESC
                    """,
                    (run_ids or [uuid4()],),
                )
                result_rows = cursor.fetchall()
        return run_rows, result_rows

    run_rows, result_rows = _run_db_operation("list_evaluation_runs", callback)
    results_by_run: dict[UUID, list[EvaluationResultRecord]] = {}
    for row in result_rows:
        results_by_run.setdefault(row["run_id"], []).append(
            EvaluationResultRecord(
                result_id=row["id"],
                run_id=row["run_id"],
                case_name=row.get("case_name"),
                question=row["question"],
                document_ids=[UUID(value) for value in row.get("document_ids", [])],
                retrieval_passed=row["retrieval_passed"],
                retrieved_source_match=row["retrieved_source_match"],
                expected_terms_found=row.get("expected_terms_found", {}),
                expected_terms_passed=row["expected_terms_passed"],
                answer_generated=row["answer_generated"],
                citations_present=row["citations_present"],
                latency_ms=row["latency_ms"],
                expected_source_file=row.get("expected_source_file"),
                expected_page_number=row.get("expected_page_number"),
                answer_preview=row.get("answer_preview"),
                created_at=row["created_at"],
            )
        )

    return [
        EvaluationRunResponse(
            run_id=row["id"],
            run_mode=row["run_mode"],
            case_count=row["case_count"],
            passed_count=row["passed_count"],
            created_at=row["created_at"],
            results=results_by_run.get(row["id"], []),
        )
        for row in run_rows
    ]
