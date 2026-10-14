"""Конфигурация сервиса.

Все параметры читаются из переменных окружения / файла .env и имеют
безопасные значения по умолчанию. Реальные секреты в репозитории не хранятся.

Ключевые группы настроек:
  * HOST/PORT            — где слушает API (по умолчанию только localhost);
  * OLLAMA_*             — адрес и модель локального Ollama;
  * RATE_LIMIT           — ограничение частоты запросов;
  * MAX_*                — ограничения контекста и вывода.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Верхняя оценка токенов для heuristic-режима — число байтов UTF-8 текста.
# В токенизаторах с byte fallback один байт может потребовать отдельный токен;
# поэтому такая оценка безопаснее, чем фиксированное отношение символов к токенам.
# Она намеренно завышает оценку для многих обычных текстов.
UTF8_BYTES_PER_TOKEN_UPPER_BOUND = 1

# Размер контекстного окна модели llama3.2 (все варианты 1B/3B) — 131072 токена.
# Это «потолок» модели, но не повод использовать его целиком: чем больше
# контекст, тем больше RAM/VRAM и медленнее генерация.
LLAMA32_CONTEXT_LENGTH = 131_072


class Settings(BaseSettings):
    """Настройки приложения, собранные из окружения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----------------------------- Сеть ---------------------------------
    host: str = Field(default="127.0.0.1", description="Адрес прослушивания API")
    port: int = Field(default=5012, ge=1, le=65535)

    # ----------------------------- Логи ---------------------------------
    log_level: Literal["SILENT", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"

    # ----------------------------- API key ------------------------------
    # Оставьте пустым в loopback-only режиме. Для доступа из LAN задайте
    # криптографически случайный ключ минимум из 32 символов.
    api_key: str | None = Field(default=None, min_length=32, max_length=256)

    # ------------------- OpenAI-совместимый доступ ----------------------
    # Имя модели, которое видит клиент в GET /v1/models и передаёт в
    # POST /v1/chat/completions. Должно совпадать с моделью агента (local-llm).
    openai_model_alias: str = Field(default="local-llm", min_length=1, max_length=128)
    # Отдельный ключ для OpenAI-совместимых маршрутов. Если задан, он принимается
    # в Authorization: Bearer или X-API-Key в дополнение к API_KEY.
    openai_api_key: str | None = Field(default=None, min_length=8, max_length=256)
    # Защищать GET /v1/models тем же ключом; OpenAI SDK передаёт его автоматически.
    openai_require_api_key_for_models: bool = True

    # ---------------------------- Ollama --------------------------------
    ollama_base_url: str = Field(default="http://127.0.0.1:11434")
    # Для модели на другом доверенном домашнем компьютере включайте явно;
    # по умолчанию удалённый/публичный endpoint блокируется.
    allow_remote_ollama: bool = False
    ollama_model: str = Field(default="llama3.2:3b", min_length=1, max_length=128)
    ollama_timeout: float = Field(default=120.0, gt=0, le=3600)
    ollama_connect_timeout: float = Field(default=5.0, gt=0, le=60)
    ollama_max_retries: int = Field(default=1, ge=0, le=5)
    ollama_num_ctx: int = Field(default=4608, ge=512, le=LLAMA32_CONTEXT_LENGTH)
    # 0 = без ограничения одновременных обращений к Ollama.
    ollama_max_concurrency: int = Field(default=1, ge=0, le=64)

    # ------------------------- Ограничения контекста --------------------
    max_message_chars: int = Field(default=4000, ge=1, le=1_000_000)
    max_history_messages: int = Field(default=20, ge=1, le=10_000)
    max_context_tokens: int = Field(default=4096, ge=1, le=LLAMA32_CONTEXT_LENGTH)
    max_output_tokens: int = Field(default=512, ge=1, le=LLAMA32_CONTEXT_LENGTH)
    context_token_tolerance: float = Field(default=0.05, ge=0.0, le=1.0)
    tokenizer: Literal["heuristic", "tiktoken"] = "heuristic"

    # ----------------------------- Rate limit ---------------------------
    rate_limit: str = Field(default="10/minute")
    trust_proxy_headers: bool = False
    trusted_proxies: str = Field(default="127.0.0.1,::1")
    rate_limit_violation_buffer: int = Field(default=100, ge=0, le=10_000)

    # -------------------------- Журнал запросов -------------------------
    # Полные сообщения/ответы сохраняются в JSON-файлах только если включено.
    request_log_enabled: bool = True
    request_log_dir: str = "logs/requests"
    request_log_max_entries: int = Field(default=500, ge=1, le=50_000)

    # --------------------------- Валидаторы -----------------------------


    @field_validator("api_key", mode="before")
    @classmethod
    def _normalize_api_key(cls, value: object) -> object:
        """Пустая строка в .env означает отключённый API key."""
        if value == "":
            return None
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def _normalize_openai_api_key(cls, value: object) -> object:
        """Пустая строка в .env означает отключённый OPENAI_API_KEY."""
        if value == "":
            return None
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("ollama_base_url")
    @classmethod
    def _normalize_base_url(cls, value: str) -> str:
        """Убираем завершающий слэш, чтобы не получить двойной в путях."""
        value = value.strip()
        if not value:
            raise ValueError("OLLAMA_BASE_URL не может быть пустым")
        from urllib.parse import urlparse

        parsed = urlparse(value)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(
                "OLLAMA_BASE_URL не должен содержать логин/пароль; используйте "
                "сетевую изоляцию без credentials в URL"
            )
        if parsed.query or parsed.fragment:
            raise ValueError("OLLAMA_BASE_URL не должен содержать query или fragment")
        return value.rstrip("/")

    @field_validator("host")
    @classmethod
    def _validate_host(cls, value: str) -> str:
        """Проверяем, что HOST — это корректный IP или имя интерфейса."""
        value = value.strip()
        if not value:
            raise ValueError("HOST не может быть пустым")
        if value in {"localhost", "0.0.0.0", "::"}:
            return value
        try:
            ipaddress.ip_address(value)
        except ValueError as exc:  # разрешаем DNS-имена, но проверяем формат
            if not all(part.replace("-", "").isalnum() for part in value.split(".")):
                raise ValueError(f"Некорректный HOST: {value!r}") from exc
        return value

    @field_validator("rate_limit")
    @classmethod
    def _validate_rate_limit(cls, value: str) -> str:
        """Проверяем формат '<число>/<период>' на этапе старта приложения."""
        raw = value.strip().lower()
        if "/" not in raw:
            raise ValueError("RATE_LIMIT должен иметь вид '10/minute'")
        amount, _, period = raw.partition("/")
        if not amount.isdigit() or int(amount) < 1:
            raise ValueError("Количество запросов в RATE_LIMIT должно быть целым числом >= 1")
        if period not in {"second", "minute", "hour", "day"}:
            raise ValueError(
                "Период в RATE_LIMIT должен быть одним из: second, minute, hour, day"
            )
        return f"{int(amount)}/{period}"

    @model_validator(mode="after")
    def _check_context_budget(self) -> "Settings":
        """Проверяем согласованность бюджета контекста.

        Входной контекст (max_context_tokens) и резерв под ответ
        (max_output_tokens) вместе не должны превышать окно, которое
        запрашивается у Ollama (ollama_num_ctx). Иначе модель молча обрежет
        либо промпт, либо ответ.
        """
        budget = self.max_context_tokens + self.max_output_tokens
        if budget > self.ollama_num_ctx:
            raise ValueError(
                "Несогласованная конфигурация контекста: "
                f"MAX_CONTEXT_TOKENS ({self.max_context_tokens}) + "
                f"MAX_OUTPUT_TOKENS ({self.max_output_tokens}) = {budget} "
                f"превышает OLLAMA_NUM_CTX ({self.ollama_num_ctx}). "
                "Увеличьте OLLAMA_NUM_CTX или уменьшите лимиты."
            )
        if not self.ollama_endpoint_is_local and not self.allow_remote_ollama:
            raise ValueError(
                "OLLAMA_BASE_URL указывает не на loopback. По умолчанию удалённая "
                "Ollama блокируется; если это ваш доверенный узел домашней сети, "
                "явно задайте ALLOW_REMOTE_OLLAMA=true. Не используйте публичный endpoint."
            )
        return self

    @property
    def rate_limit_amount(self) -> int:
        """Число запросов в окне ограничения."""
        return int(self.rate_limit.split("/", 1)[0])

    @property
    def rate_limit_period(self) -> str:
        """Период окна ограничения (second/minute/hour/day)."""
        return self.rate_limit.split("/", 1)[1]

    @property
    def rate_limit_window_seconds(self) -> int:
        """Длительность окна ограничения в секундах."""
        return {
            "second": 1,
            "minute": 60,
            "hour": 3600,
            "day": 86400,
        }[self.rate_limit_period]

    @property
    def trusted_proxy_list(self) -> tuple[str, ...]:
        """Список доверенных прокси в виде кортежа строк."""
        return tuple(
            item.strip() for item in self.trusted_proxies.split(",") if item.strip()
        )

    @property
    def context_token_budget(self) -> int:
        """Бюджет оценки входных токенов с резервом на погрешность токенизатора."""
        return int(self.max_context_tokens * (1.0 - self.context_token_tolerance))

    @property
    def is_public_bind(self) -> bool:
        """True, если API слушает не только localhost (небезопасный режим)."""
        return self.host not in {"127.0.0.1", "::1", "localhost"}

    @property
    def ollama_endpoint_is_local(self) -> bool:
        """True, если Ollama настроена на loopback-адрес.

        Используется только для информационного предупреждения при старте:
        обращение к Ollama по не-loopback адресу может означать, что модель
        работает на другом устройстве, и это стоит осознавать.
        """
        try:
            from urllib.parse import urlparse

            host = urlparse(self.ollama_base_url).hostname or ""
            if host in {"localhost"}:
                return True
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает единственный экземпляр настроек (кэшируется).

    Кэш можно сбросить в тестах через ``get_settings.cache_clear()``.
    """
    return Settings()
