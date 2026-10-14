"""Изменяемые на лету настройки сервиса.

Базовые значения берутся из окружения/`.env` (класс ``Settings``). Через веб-панель
можно менять «живой» набор runtime-параметров, не перезапуская процесс:

* модель, адрес и таймауты Ollama;
* контекстное окно ``num_ctx``;
* лимиты размера сообщения, истории, входного контекста и вывода;
* ограничение частоты запросов;
* включение журнала запросов.

Что НЕ меняется на лету (осознанно):

* ``HOST``/``PORT`` — адрес прослушивания задаётся при старте Uvicorn;
* ``API_KEY`` — секреты не хранятся в панели и не возвращаются по API;
* путь и лимит записей журнала — чтобы не перенаправлять запись файлов
  произвольным вводом.

Runtime-значения живут только в памяти процесса и сбрасываются при
перезапуске. Кнопка «Сбросить» возвращает значения из `.env`.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import HTTPException

from .config import Settings
from .schemas import RuntimeSettingsPatch

logger = logging.getLogger("app.settings_store")

# Поля Settings, которые можно менять через панель.
EDITABLE_FIELDS: tuple[str, ...] = (
    "ollama_model",
    "ollama_base_url",
    "ollama_timeout",
    "ollama_connect_timeout",
    "ollama_num_ctx",
    "ollama_max_concurrency",
    "max_message_chars",
    "max_history_messages",
    "max_context_tokens",
    "max_output_tokens",
    "context_token_tolerance",
    "rate_limit",
    "request_log_enabled",
)

# Секреты и адрес прослушивания: только для чтения, значения не раскрываются.
READ_ONLY_FIELDS: tuple[str, ...] = (
    "host",
    "port",
    "api_key",
    "openai_api_key",
    "openai_model_alias",
    "openai_require_api_key_for_models",
    "trust_proxy_headers",
    "trusted_proxies",
    "request_log_dir",
    "request_log_max_entries",
    "tokenizer",
    "log_level",
)

# Значения, которые нельзя менять на лету, хотя поле существует в Settings.
IMMUTABLE_FIELDS: tuple[str, ...] = (
    "host",
    "port",
    "api_key",
    "openai_api_key",
    "openai_model_alias",
    "openai_require_api_key_for_models",
    "trust_proxy_headers",
    "trusted_proxies",
    "tokenizer",
    "request_log_dir",
    "request_log_max_entries",
    "log_level",
)


class SettingsStore:
    """Хранит текущие настройки и умеет атомарно их заменять.

    Объект ``Settings`` неизменяем (frozen-подобная валидация Pydantic),
    поэтому замена выполняется целиком через ``model_copy(update=...)``.
    Это гарантирует, что проверки согласованности (например,
    ``MAX_CONTEXT_TOKENS + MAX_OUTPUT_TOKENS <= OLLAMA_NUM_CTX``) применяются
    к новому набору до его публикации.
    """

    def __init__(self, settings: Settings) -> None:
        self._baseline = settings
        self._current = settings

    @property
    def baseline(self) -> Settings:
        """Настройки из окружения/`.env` — эталон для сброса."""
        return self._baseline

    @property
    def current(self) -> Settings:
        """Действующие настройки процесса."""
        return self._current

    def is_modified(self) -> bool:
        """True, если действующие настройки отличаются от `.env`."""
        return self._editable_snapshot(self._current) != self._editable_snapshot(
            self._baseline
        )

    @staticmethod
    def _editable_snapshot(settings: Settings) -> dict[str, Any]:
        return {field: getattr(settings, field) for field in EDITABLE_FIELDS}

    def as_payload(self) -> dict[str, Any]:
        """Возвращает безопасное представление настроек для панели.

        Значение ``api_key`` не раскрывается: вместо него передаётся признак
        того, что аутентификация включена.
        """
        current = self._current
        baseline = self._baseline
        editable = self._editable_snapshot(current)
        baseline_editable = self._editable_snapshot(baseline)
        read_only = {
            field: getattr(current, field)
            for field in READ_ONLY_FIELDS
            if field != "api_key"
        }
        read_only["api_key_configured"] = bool(current.api_key)
        read_only["openai_api_key_configured"] = bool(current.openai_api_key)
        return {
            "settings": editable,
            "env_values": baseline_editable,
            "read_only": read_only,
            "immutable_fields": list(IMMUTABLE_FIELDS),
            "rate_limit": {
                "expression": current.rate_limit,
                "amount": current.rate_limit_amount,
                "period": current.rate_limit_period,
                "window_seconds": current.rate_limit_window_seconds,
            },
            "context_budget": {
                "max_context_tokens": current.max_context_tokens,
                "max_output_tokens": current.max_output_tokens,
                "ollama_num_ctx": current.ollama_num_ctx,
                "safety_margin_tokens": current.max_context_tokens
                - current.context_token_budget,
                "evaluation_budget": current.context_token_budget,
            },
            "modified": self.is_modified(),
            "restart_required_for": ["HOST", "PORT", "API_KEY", "TOKENIZER"],
        }

    def update(self, patch: RuntimeSettingsPatch) -> dict[str, Any]:
        """Применяет частичное обновление и возвращает новое представление.

        Неизвестные и неизменяемые поля отклоняются с HTTP 400, некорректные
        значения — с HTTP 422 и понятным сообщением.
        """
        changes = patch.model_dump(exclude_unset=True, exclude_none=True)
        unknown = set(changes) - set(EDITABLE_FIELDS)
        if unknown:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "unknown_setting",
                    "message": (
                        "Поле нельзя изменить: "
                        + ", ".join(sorted(unknown))
                        + ". Изменяемые поля: "
                        + ", ".join(EDITABLE_FIELDS)
                    ),
                    "details": {"unknown_fields": sorted(unknown)},
                },
            )
        if not changes:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "empty_update",
                    "message": "Не передано ни одного изменяемого параметра.",
                    "details": None,
                },
            )

        try:
            candidate = self._current.model_copy(update=changes)
        except Exception as exc:  # ошибки сборки модели Pydantic
            logger.warning("Отклонено обновление настроек: %s", type(exc).__name__)
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_setting",
                    "message": "Значение параметра некорректно.",
                    "details": None,
                },
            ) from exc

        # Пересобираем через конструктор, чтобы гарантированно выполнить
        # кросс-валидацию (бюджет контекста, формат RATE_LIMIT и т.п.).
        try:
            validated = Settings(**candidate.model_dump())
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_setting",
                    "message": str(exc).split("\n")[0],
                    "details": None,
                },
            ) from exc

        self._current = validated
        logger.info(
            "Настройки обновлены на лету: %s",
            ", ".join(sorted(changes)),
        )
        return self.as_payload()

    def reset(self) -> dict[str, Any]:
        """Возвращает значения из `.env` (перезапуск не требуется)."""
        self._current = self._baseline
        logger.info("Настройки сброшены к значениям из .env")
        return self.as_payload()


def settings_diff(settings: Settings, patch: RuntimeSettingsPatch) -> dict[str, Any]:
    """Вспомогательная функция для тестов: что изменится при применении патча."""
    changes = patch.model_dump(exclude_unset=True, exclude_none=True)
    return {
        field: {"from": getattr(settings, field), "to": value}
        for field, value in changes.items()
        if field in EDITABLE_FIELDS
    }


def dataclass_to_dict(value: Any) -> dict[str, Any]:
    """Преобразует dataclass в словарь (используется журналом запросов)."""
    return asdict(value)
