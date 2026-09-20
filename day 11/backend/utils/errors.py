"""Custom exceptions and user-facing error messages."""

from __future__ import annotations

from typing import Optional


class AppError(Exception):
    """Base class for application errors that map to HTTP responses."""

    status_code: int = 500
    code: str = "internal_error"
    default_message: str = "Внутренняя ошибка приложения."

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        detail: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> None:
        self.message = message or self.default_message
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.message)

    def to_payload(self) -> dict:
        payload = {"error": {"code": self.code, "message": self.message}}
        if self.detail:
            payload["error"]["detail"] = self.detail
        return payload


class SettingsNotConfiguredError(AppError):
    status_code = 400
    code = "settings_not_configured"
    default_message = (
        "API не настроен. Укажите Base URL и API Key в настройках."
    )


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"
    default_message = "Некорректные данные запроса."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    default_message = "Объект не найден."


class AIClientError(AppError):
    """Error raised by the OpenAI-compatible client."""

    status_code = 502
    code = "api_error"
    default_message = (
        "Не удалось подключиться к API.\n\n"
        "Проверьте:\n"
        "• API URL\n"
        "• API Key\n"
        "• доступность сервера"
    )


class AIConnectionError(AIClientError):
    code = "api_unreachable"
    default_message = (
        "Не удалось подключиться к API.\n\n"
        "Проверьте:\n"
        "• API URL\n"
        "• API Key\n"
        "• доступность сервера"
    )


class AITimeoutError(AIClientError):
    code = "api_timeout"
    default_message = (
        "Превышено время ожидания ответа от API.\n"
        "Сервер не ответил вовремя — попробуйте ещё раз."
    )


class AIAuthError(AIClientError):
    status_code = 401
    code = "api_auth_error"
    default_message = (
        "API отклонил запрос авторизации.\n\n"
        "Проверьте API Key и права доступа."
    )


class AIRateLimitError(AIClientError):
    status_code = 429
    code = "api_rate_limit"
    default_message = (
        "API вернул ошибку лимита запросов (429).\n"
        "Подождите немного и повторите попытку."
    )


class AIResponseFormatError(AIClientError):
    code = "api_bad_response"
    default_message = (
        "API вернул ответ в неожиданном формате.\n"
        "Проверьте, что указан OpenAI-compatible сервер."
    )


class NoModelsError(AIClientError):
    code = "no_models"
    default_message = (
        "Не удалось получить список моделей.\n"
        "Проверьте настройки API."
    )