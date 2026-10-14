"""Pydantic-модели запросов и ответов.

Здесь описаны контракты HTTP API: то, что принимает ``POST /chat``,
и то, что сервис возвращает клиенту. Схемы ошибок намеренно не содержат
внутренних деталей (путей, трассировок, текстов исключений Ollama).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Допустимые роли сообщений — ровно те, что понимает chat-API Ollama.
MessageRole = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    """Одно сообщение диалога."""

    model_config = ConfigDict(extra="forbid")

    role: MessageRole = Field(
        description="Роль автора сообщения: system, user или assistant."
    )
    content: str = Field(
        min_length=1,
        description="Текст сообщения. Пустые строки не допускаются.",
    )

    @field_validator("content")
    @classmethod
    def _content_not_blank(cls, value: str) -> str:
        """Отклоняем сообщения из одних пробелов.

        ``min_length=1`` пропускает строку из пробелов, поэтому проверяем
        наличие непробельных символов отдельно.
        """
        if not value.strip():
            raise ValueError("Сообщение не может быть пустым или состоять из пробелов")
        return value


class ChatRequest(BaseModel):
    """Тело запроса ``POST /chat``."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": "Привет! Расскажи, что ты умеешь.",
                        }
                    ]
                }
            ]
        },
    )

    messages: list[ChatMessage] = Field(
        min_length=1,
        description="История диалога. Последним должно идти сообщение роли user.",
    )
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Необязательная температура генерации (0.0–2.0).",
    )

    @field_validator("messages")
    @classmethod
    def _last_message_must_be_user(
        cls, value: list[ChatMessage]
    ) -> list[ChatMessage]:
        """Требуем, чтобы диалог заканчивался сообщением пользователя.

        Модель генерирует продолжение диалога; если последним сообщением
        стоит assistant, продолжать нечего, и ответ был бы бессмысленным.
        """
        if not value:
            raise ValueError("Список messages не может быть пустым")
        if value[-1].role != "user":
            raise ValueError(
                "Последнее сообщение в messages должно иметь роль 'user'"
            )
        return value


class ChatResponse(BaseModel):
    """Успешный ответ ``POST /chat``."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "response": "Привет! Я могу отвечать на вопросы и помогать с задачами.",
                    "model": "llama3.2:3b",
                    "done": True,
                }
            ]
        }
    )

    response: str = Field(description="Текст ответа локальной модели.")
    model: str = Field(description="Имя модели, сгенерировавшей ответ.")
    done: bool = Field(default=True, description="Генерация завершена полностью.")


class LiveStatus(BaseModel):
    """Ответ ``GET /health/live``: процесс API жив."""

    status: Literal["ok"] = "ok"
    service: str = "local-llm-service"
    version: str


class HealthStatus(BaseModel):
    """Ответ ``GET /health``: состояние API и локального Ollama."""

    status: Literal["ok", "degraded"]
    api: Literal["ok"] = "ok"
    ollama: Literal["ok", "unavailable", "model_missing", "error"]
    ollama_url: str = Field(description="Адрес Ollama (без учётных данных).")
    model: str
    model_available: bool
    detail: str = Field(description="Понятное человеку пояснение состояния.")


class ErrorDetail(BaseModel):
    """Внутренняя часть тела ошибки."""

    code: str = Field(description="Машиночитаемый код ошибки.")
    message: str = Field(description="Понятное описание без внутренних деталей.")
    # Дополнительные безопасные сведения: имя превышенного лимита,
    # фактические и предельные значения. Внутренних путей и трассировок здесь нет.
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """Единый формат ошибки для всех маршрутов."""

    error: ErrorDetail


# =====================================================================
#  Веб-панель управления
# =====================================================================


class RuntimeSettingsPatch(BaseModel):
    """Частичное обновление настроек на лету.

    Все поля необязательны: передаются только те, которые нужно изменить.
    Допустимые диапазоны описаны здесь, а кросс-проверки (например,
    бюджет контекста и формат RATE_LIMIT) выполняет ``app.config.Settings``.
    """

    model_config = ConfigDict(extra="forbid")

    ollama_model: str | None = Field(default=None, min_length=1, max_length=128)
    ollama_base_url: str | None = Field(default=None, max_length=256)
    ollama_timeout: float | None = Field(default=None, gt=0, le=3600)
    ollama_connect_timeout: float | None = Field(default=None, gt=0, le=60)
    ollama_num_ctx: int | None = Field(default=None, ge=512, le=131072)
    ollama_max_concurrency: int | None = Field(default=None, ge=0, le=64)
    max_message_chars: int | None = Field(default=None, ge=1, le=1_000_000)
    max_history_messages: int | None = Field(default=None, ge=1, le=10_000)
    max_context_tokens: int | None = Field(default=None, ge=1, le=131072)
    max_output_tokens: int | None = Field(default=None, ge=1, le=131072)
    context_token_tolerance: float | None = Field(default=None, ge=0.0, le=1.0)
    rate_limit: str | None = Field(
        default=None,
        max_length=32,
        description="Формат '<число>/<period>', например '10/minute'.",
    )
    request_log_enabled: bool | None = None


class OllamaProbeRequest(BaseModel):
    """Проверка произвольной пары адрес+модель перед применением."""

    model_config = ConfigDict(extra="forbid")

    ollama_base_url: str | None = Field(default=None, max_length=256)
    ollama_model: str | None = Field(default=None, min_length=1, max_length=128)


class OllamaModelInfo(BaseModel):
    """Краткая информация об установленной модели."""

    name: str
    size_bytes: int | None = None
    family: str | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    context_length: int | None = None


class OllamaProbeResponse(BaseModel):
    """Результат проверки доступности модели."""

    reachable: bool
    model_available: bool
    installed_models: list[str] = Field(default_factory=list)
    detail: str
    current_model: str
    base_url: str


class RequestLogSummary(BaseModel):
    """Краткая запись журнала (без содержимого сообщений)."""

    id: str
    started_at: str
    client: str
    model: str
    status: str
    http_status: int | None = None
    error_code: str | None = None
    duration_ms: float | None = None
    message_count: int = 0
    estimated_input_tokens: int | None = None
    response_chars: int | None = None
    file: str | None = None


class RequestLogEntry(RequestLogSummary):
    """Полная запись журнала, включая тексты сообщений и ответ."""

    finished_at: str | None = None
    ollama_base_url: str = ""
    error_message: str | None = None
    roles: list[str] = Field(default_factory=list)
    max_output_tokens: int | None = None
    num_ctx: int | None = None
    messages: list[dict[str, str]] = Field(default_factory=list)
    response: str | None = None


class RequestLogPage(BaseModel):
    """Страница журнала запросов."""

    total: int
    limit: int
    offset: int
    items: list[RequestLogSummary]


class RequestLogStats(BaseModel):
    """Сводка по хранилищу журнала."""

    enabled: bool
    directory: str
    files: int
    buffered: int
    max_entries: int
    write_errors: int


# =====================================================================
#  Минимальная совместимость с OpenAI Chat Completions API
# =====================================================================


class OpenAIChatMessage(BaseModel):
    """Текстовое сообщение OpenAI-style chat.

    Поддерживаются только роли system/user/assistant и строковый content.
    Мультимодальные parts, tools/function calling, роли developer и tool
    намеренно не принимаются.
    """

    # strict=True не даёт Pydantic молча приводить числа/строки к строкам;
    # контракт OpenAI SDK для этих полей — именно строки.
    model_config = ConfigDict(extra="forbid", strict=True)

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)
    name: str | None = Field(default=None, max_length=128)

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content не может быть пустым")
        return value


class OpenAIChatCompletionRequest(BaseModel):
    """Поддерживаемое подмножество Chat Completions request.

    Не поддерживается (отклоняется с HTTP 400 и понятным сообщением):
    tools/function calling, мультимодальный content-массив, response_format,
    n>1, logprobs и роли developer/tool. Параметр ``stream_options``
    принимается ради совместимости с клиентами, но include_usage игнорируется.
    """

    # strict=True: stream="yes" или max_tokens="64" — ошибка, а не молчаливое
    # приведение типов. Так ведёт себя и настоящий OpenAI API.
    model_config = ConfigDict(extra="forbid", strict=True)

    model: str = Field(min_length=1, max_length=128)
    messages: list[OpenAIChatMessage] = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=131072)
    stream: bool = False
    # Некоторые OpenAI-клиенты (в том числе агенты) автоматически добавляют
    # stream_options при stream=true. Запрос с ним должен выполняться, а не
    # падать: собственный usage-чанк в потоке мы не выдаём и не подделываем.
    stream_options: dict[str, Any] | None = Field(default=None)

    @field_validator("messages")
    @classmethod
    def _last_message_must_be_user(cls, value: list[OpenAIChatMessage]):
        if not value or value[-1].role != "user":
            raise ValueError("Последнее сообщение должно иметь роль user")
        return value


class OpenAIModelCard(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = 0
    owned_by: str = "local"


class OpenAIModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[OpenAIModelCard]


class OpenAIUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class OpenAIChatChoice(BaseModel):
    index: int = 0
    message: dict[str, str]
    finish_reason: Literal["stop", "length"] = "stop"


class OpenAIChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[OpenAIChatChoice]
    # Если Ollama не возвращает фактические eval counts, usage опускается;
    # статистика не оценивается и не подменяется выдуманными значениями.
    usage: OpenAIUsage | None = None


class OpenAIStreamDelta(BaseModel):
    role: Literal["assistant"] | None = None
    content: str | None = None


class OpenAIStreamChoice(BaseModel):
    index: int = 0
    delta: OpenAIStreamDelta
    finish_reason: Literal["stop", "length"] | None = None


class OpenAIChatCompletionChunk(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[OpenAIStreamChoice]


class OpenAIErrorBody(BaseModel):
    message: str
    type: str
    param: str | None = None
    code: str | None = None


class OpenAIErrorResponse(BaseModel):
    error: OpenAIErrorBody
