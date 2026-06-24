from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.core.exceptions import DependencyUnavailableError
from app.schemas.chat import LLMResponse, LLMUsage

logger = logging.getLogger(__name__)
MODEL_RATE_LIMIT_COOLDOWN_SECONDS = 60
RATE_LIMITED_MESSAGE = "The configured chat model is temporarily rate-limited upstream. Please try again shortly."
_model_cooldowns: dict[str, float] = {}

def _coerce_message_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()

    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts).strip()

    return ""

def _parse_llm_response(payload: dict[str, Any], *, fallback_used: bool) -> LLMResponse:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise DependencyUnavailableError("Language model service is temporarily unavailable.")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise DependencyUnavailableError("Language model service is temporarily unavailable.")

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise DependencyUnavailableError("Language model service is temporarily unavailable.")

    answer = _coerce_message_content(message.get("content"))
    if not answer:
        raise DependencyUnavailableError("Language model service is temporarily unavailable.")

    usage_payload = payload.get("usage")
    usage = LLMUsage()
    if isinstance(usage_payload, dict):
        usage = LLMUsage(
            prompt_tokens=usage_payload.get("prompt_tokens"),
            completion_tokens=usage_payload.get("completion_tokens"),
            total_tokens=usage_payload.get("total_tokens"),
        )

    model_used = payload.get("model")
    if not isinstance(model_used, str) or not model_used:
        model_used = "unknown"

    return LLMResponse(
        answer=answer,
        model_used=model_used,
        usage=usage,
        fallback_used=fallback_used,
        raw_response_metadata={
            "id": payload.get("id"),
            "provider": payload.get("provider"),
        },
    )

def _is_rate_limit_error(error: Exception) -> bool:
    return isinstance(error, DependencyUnavailableError) and error.detail == RATE_LIMITED_MESSAGE

def _prune_model_cooldowns(now: float) -> None:
    expired_models = [
        model_name
        for model_name, blocked_until in _model_cooldowns.items()
        if blocked_until <= now
    ]
    for model_name in expired_models:
        _model_cooldowns.pop(model_name, None)

def _mark_model_cooldown(model_name: str, *, now: float | None = None) -> None:
    current_time = now if now is not None else time.monotonic()
    _model_cooldowns[model_name] = current_time + MODEL_RATE_LIMIT_COOLDOWN_SECONDS

def _is_model_in_cooldown(model_name: str, *, now: float | None = None) -> bool:
    current_time = now if now is not None else time.monotonic()
    blocked_until = _model_cooldowns.get(model_name)
    return blocked_until is not None and blocked_until > current_time

def _perform_openrouter_request(
    *,
    model_name: str,
    messages: list[dict[str, str]],
    settings: Settings,
) -> dict[str, Any]:
    if not settings.openrouter_api_key:
        logger.warning("OpenRouter call failed because OPENROUTER_API_KEY is not configured.")
        raise DependencyUnavailableError("Language model service is temporarily unavailable.")

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
    }
    timeout = httpx.Timeout(
        timeout=settings.llm_timeout_seconds,
        connect=min(settings.llm_timeout_seconds, 10.0),
    )

    started_at = time.perf_counter()

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                settings.openrouter_base_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            elapsed_ms = round((time.perf_counter() - started_at) * 1000)
            logger.info(
                "OpenRouter model request succeeded model=%s elapsed_ms=%s status=%s",
                model_name,
                elapsed_ms,
                response.status_code,
            )
            return response.json()
    except httpx.HTTPStatusError as exc:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        response_body = exc.response.text
        detail = "Language model service is temporarily unavailable."
        if exc.response.status_code == 429:
            _mark_model_cooldown(model_name)
            detail = RATE_LIMITED_MESSAGE
        logger.warning(
            "OpenRouter model request failed model=%s status=%s elapsed_ms=%s response=%s",
            model_name,
            exc.response.status_code,
            elapsed_ms,
            response_body[:500],
        )
        raise DependencyUnavailableError(detail) from exc
    except (
        httpx.TimeoutException,
        httpx.RequestError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        logger.warning(
            "OpenRouter model request failed model=%s elapsed_ms=%s because %s",
            model_name,
            elapsed_ms,
            exc.__class__.__name__,
            exc_info=True,
        )
        if isinstance(exc, httpx.TimeoutException):
            raise DependencyUnavailableError("The chat model took too long to respond. Please try again shortly.") from exc

        raise DependencyUnavailableError("Language model service is temporarily unavailable.") from exc

def generate_chat_completion(
    messages: list[dict[str, str]],
    settings: Settings | None = None,
) -> LLMResponse:
    current_settings = settings or get_settings()
    model_attempts: list[str] = [current_settings.openrouter_model_primary]
    if current_settings.openrouter_model_fallback != current_settings.openrouter_model_primary:
        model_attempts.append(current_settings.openrouter_model_fallback)

    now = time.monotonic()
    _prune_model_cooldowns(now)
    available_model_attempts = [
        model_name for model_name in model_attempts if not _is_model_in_cooldown(model_name, now=now)
    ] or model_attempts

    last_error: DependencyUnavailableError | None = None
    non_rate_limit_error: DependencyUnavailableError | None = None
    for index, model_name in enumerate(available_model_attempts):
        try:
            payload = _perform_openrouter_request(
                model_name=model_name,
                messages=messages,
                settings=current_settings,
            )
            return _parse_llm_response(payload, fallback_used=index > 0)
        except DependencyUnavailableError as exc:
            last_error = exc
            if not _is_rate_limit_error(exc):
                non_rate_limit_error = exc
            if index == 0 and len(available_model_attempts) > 1:
                logger.warning(
                    "OpenRouter primary model failed model=%s; trying fallback model=%s",
                    available_model_attempts[0],
                    available_model_attempts[1],
                )
                continue
            break

    if non_rate_limit_error is not None:
        raise non_rate_limit_error

    if last_error is not None:
        raise last_error

    raise DependencyUnavailableError("Language model service is temporarily unavailable.")
