"""Ограничение частоты запросов и контроль размера контекста.

Rate limit реализован как атомарный fixed-window счётчик в памяти процесса:
максимум N запросов от одного IP за выбранный период. Это подходящий,
прозрачный механизм для локального учебного сервиса; он не является
распределённой системой и не объединяет счётчики нескольких worker-процессов.

Контекст проверяется до обращения к Ollama по трём лимитам:
  * максимальная длина отдельного сообщения (символы);
  * максимальное количество сообщений в истории;
  * оценка входных токенов по всей истории + системным инструкциям.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, Request

from .config import Settings, UTF8_BYTES_PER_TOKEN_UPPER_BOUND
from .schemas import ChatMessage
from .security import get_client_identifier

logger = logging.getLogger("app.limits")


@dataclass(frozen=True)
class ContextCheckResult:
    """Результат проверки запроса на соответствие лимитам контекста."""

    ok: bool
    reason: Literal[
        "ok",
        "too_many_messages",
        "message_too_long",
        "context_too_large",
        "invalid_history",
    ] = "ok"
    message: str = ""
    details: dict[str, object] | None = None
    http_status: int = 200
    estimated_tokens: int = 0


class InMemoryRateLimiter:
    """Потокобезопасный fixed-window rate limiter в памяти одного процесса.

    Счётчик хранит время начала окна и количество запросов для каждого
    клиента. Блокировка защищает изменение словаря при многопоточной работе.
    Просроченные ключи периодически удаляются, чтобы словарь не рос бесконечно.

    Ограничения: счётчики сбрасываются при перезапуске процесса и не общие
    между несколькими worker-процессами. Для нескольких инстансов понадобится
    общий backend, например Redis; в локальном однопроцессном запуске это
    не требуется.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()
        self._calls = 0

    def check(self, key: str, *, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Проверяет и регистрирует запрос.

        Возвращает ``(allowed, retry_after_seconds)``. Неуспешные запросы
        тоже считаются: это защищает от бесконечной отправки некорректных
        или слишком больших тел.
        """
        now = time.monotonic()
        with self._lock:
            self._calls += 1
            if self._calls % 256 == 0:
                cutoff = now - max(window_seconds * 2, 86400)
                self._buckets = {
                    client: entry
                    for client, entry in self._buckets.items()
                    if entry[0] >= cutoff
                }

            started, count = self._buckets.get(key, (now, 0))
            if now - started >= window_seconds:
                started, count = now, 0

            if count >= limit:
                retry_after = max(1, math.ceil(window_seconds - (now - started)))
                return False, retry_after

            self._buckets[key] = (started, count + 1)
            return True, 0

    def reset(self) -> None:
        """Очищает все счётчики (для автоматических тестов)."""
        with self._lock:
            self._buckets.clear()
            self._calls = 0


async def enforce_rate_limit(request: Request) -> None:
    """FastAPI dependency, применяемая к POST /chat."""
    settings: Settings = request.app.state.settings
    limiter: InMemoryRateLimiter = request.app.state.rate_limiter
    client = get_client_identifier(request, settings)
    allowed, retry_after = limiter.check(
        client,
        limit=settings.rate_limit_amount,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if allowed:
        return

    violations = request.app.state.rate_limit_violations
    violations.add(client=client, route=request.url.path)
    logger.warning(
        "Rate limit превышен: client=%s route=%s limit=%s",
        client,
        request.url.path,
        settings.rate_limit,
    )
    raise HTTPException(
        status_code=429,
        detail={
            "code": "rate_limit_exceeded",
            "message": (
                "Слишком много запросов. "
                f"Лимит: {settings.rate_limit}. "
                f"Повторите попытку примерно через {retry_after} с."
            ),
            "details": {
                "limit": settings.rate_limit,
                "retry_after_seconds": retry_after,
                "window_seconds": settings.rate_limit_window_seconds,
            },
        },
        headers={"Retry-After": str(retry_after)},
    )


class ContextLimiter:
    """Считает токены запроса и отклоняет слишком большие контексты.

    Считаются все части промпта: системные инструкции, история диалога
    и новое сообщение пользователя. Плюс резерв под ответ модели
    (``max_output_tokens``), который уже учтён в проверке согласованности
    настроек ``MAX_CONTEXT_TOKENS + MAX_OUTPUT_TOKENS <= OLLAMA_NUM_CTX``.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._encoding = self._load_encoding(settings.tokenizer)

    @staticmethod
    def _load_encoding(tokenizer: str):
        """Пробует загрузить BPE-токенизатор, если он выбран явно."""
        if tokenizer != "tiktoken":
            return None
        try:
            import tiktoken  # type: ignore
        except ImportError:
            logger.warning(
                "TOKENIZER=tiktoken, но пакет tiktoken не установлен. "
                "Используется консервативная эвристика."
            )
            return None
        # cl100k_base не совпадает с SentencePiece/токенизатором Llama.
        # Поэтому мы называем это оценкой, а не точным подсчётом токенов.
        return tiktoken.get_encoding("cl100k_base")

    @property
    def tokenizer_name(self) -> str:
        """Имя фактически используемого способа подсчёта токенов."""
        return "tiktoken:cl100k_base (приближение)" if self._encoding is not None else "heuristic"

    def count_tokens(self, text: str) -> int:
        """Оценивает количество токенов.

        При использовании эвристики применяется верхняя оценка по UTF-8:
        каждый байт считается отдельным токеном. Это намеренно завышает
        оценку для многих текстов и безопаснее недооценки длины контекста.
        Эвристика всё равно не является точным токенизатором конкретной модели.
        """
        if not text:
            return 0
        if self._encoding is not None:
            return len(self._encoding.encode(text))
        return len(text.encode("utf-8")) * UTF8_BYTES_PER_TOKEN_UPPER_BOUND

    def estimate_messages_tokens(self, messages: list[ChatMessage]) -> int:
        """Суммарная оценка токенов по сообщениям и маркерам ролей."""
        per_message_overhead = 4
        return sum(
            self.count_tokens(message.content) + per_message_overhead
            for message in messages
        )

    def check(self, messages: list[ChatMessage]) -> ContextCheckResult:
        """Проверяет запрос целиком и возвращает результат проверки."""
        settings = self.settings

        # 1. Максимальное количество сообщений в истории.
        if len(messages) > settings.max_history_messages:
            return ContextCheckResult(
                ok=False,
                reason="too_many_messages",
                http_status=413,
                message=(
                    "Слишком длинная история сообщений: "
                    f"{len(messages)} при допустимом максимуме "
                    f"{settings.max_history_messages}."
                ),
                details={
                    "limit_name": "MAX_HISTORY_MESSAGES",
                    "limit": settings.max_history_messages,
                    "actual": len(messages),
                },
            )

        # 2. Максимальная длина каждого отдельного сообщения.
        for index, message in enumerate(messages):
            if len(message.content) > settings.max_message_chars:
                return ContextCheckResult(
                    ok=False,
                    reason="message_too_long",
                    http_status=413,
                    message=(
                        f"Сообщение #{index + 1} слишком длинное: "
                        f"{len(message.content)} символов при допустимом максимуме "
                        f"{settings.max_message_chars}."
                    ),
                    details={
                        "limit_name": "MAX_MESSAGE_CHARS",
                        "limit": settings.max_message_chars,
                        "actual": len(message.content),
                        "message_index": index,
                    },
                )

        # 3. System-инструкция допустима только в начале истории.
        for index, message in enumerate(messages):
            if message.role == "system" and index != 0:
                return ContextCheckResult(
                    ok=False,
                    reason="invalid_history",
                    http_status=422,
                    message=(
                        "Сообщение с ролью 'system' допускается только первым "
                        f"в списке messages (получено на позиции {index + 1})."
                    ),
                    details={"message_index": index},
                )

        # 4. Бюджет входных токенов. Допуск нужен потому, что ни эвристика,
        #    ни cl100k_base не совпадают с точным токенизатором Ollama-модели.
        estimated = self.estimate_messages_tokens(messages)
        budget = settings.context_token_budget
        if estimated > budget:
            return ContextCheckResult(
                ok=False,
                reason="context_too_large",
                http_status=413,
                message=(
                    f"Контекст слишком большой: примерно {estimated} токенов при "
                    f"допустимом максимуме {settings.max_context_tokens} "
                    f"(с резервом {settings.context_token_tolerance:.0%} на погрешность оценки). "
                    f"Сократите историю или длину сообщений. "
                    f"Резерв под ответ модели: {settings.max_output_tokens} токенов."
                ),
                details={
                    "limit_name": "MAX_CONTEXT_TOKENS",
                    "limit": settings.max_context_tokens,
                    "budget_after_safety_margin": budget,
                    "actual_estimated_tokens": estimated,
                    "reserved_output_tokens": settings.max_output_tokens,
                    "tokenizer": self.tokenizer_name,
                },
                estimated_tokens=estimated,
            )

        return ContextCheckResult(ok=True, estimated_tokens=estimated)
