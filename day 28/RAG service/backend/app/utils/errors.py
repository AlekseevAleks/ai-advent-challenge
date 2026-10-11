"""Единый формат ошибок API.

Все ошибки возвращаются как JSON: {"detail": "...", "code": "..."} с корректным HTTP-кодом.
"""

from __future__ import annotations

from typing import Any, Optional


class AppError(Exception):
    """Базовое бизнес-исключение с HTTP-статусом и кодом."""

    status_code: int = 400

    def __init__(self, message: str, code: Optional[str] = None, details: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class ValidationError2(AppError):  # noqa: N802  (избегаем конфликта с pydantic)
    status_code = 422


class UnprocessableError(AppError):
    status_code = 422


def error_payload(exc: AppError) -> dict[str, Any]:
    payload: dict[str, Any] = {"detail": exc.message}
    if exc.code:
        payload["code"] = exc.code
    if exc.details is not None:
        payload["details"] = exc.details
    return payload