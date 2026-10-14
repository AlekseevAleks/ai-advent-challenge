"""Безопасность и приватность.

Модуль отвечает за три вещи:

1. Определение идентификатора клиента для rate limit
   (``get_client_identifier``) — с осторожным отношением к заголовкам
   ``X-Forwarded-For``.
2. Маскирование потенциальных секретов перед логированием
   (``redact_secrets``).
3. Набор предупреждений о небезопасной конфигурации при старте
   (``security_warnings``).

Логика намеренно простая и не использует ``eval``/``exec`` для обработки
пользовательского текста.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import re
from collections import deque
from datetime import datetime, timezone
from typing import Deque

from fastapi import HTTPException, Request

from .config import Settings

logger = logging.getLogger("app.security")

# Шаблоны, по которым узнаются секреты в тексте. Список сознательно
# консервативный: цель — не «угадать любой секрет», а не допустить
# попадания очевидных ключей и токенов в логи.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}\b")),
    ("huggingface_token", re.compile(r"\bhf_[A-Za-z0-9]{16,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}")),
    (
        "generic_assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*['\"]?([^\s'\"]{8,})"
        ),
    ),
)


def require_api_key(request: Request) -> None:
    """Проверяет необязательный API key для POST /chat и админ-маршрутов.

    В loopback-only режиме без ``API_KEY`` аутентификация отключена.
    Если ключ настроен, разрешается передать его как ``Authorization: Bearer``
    или ``X-API-Key``. Сравнение выполняется через constant-time функцию,
    значение ключа никогда не логируется и не передаётся в URL.
    """
    require_valid_api_key(request)


def require_openai_api_key(request: Request) -> None:
    """FastAPI dependency для OpenAI-совместимых /v1 routes."""
    require_valid_api_key(request)


def require_openai_models_api_key(request: Request) -> None:
    """Защищает GET /v1/models по настройке OPENAI_REQUIRE_API_KEY_FOR_MODELS."""
    if request.app.state.settings.openai_require_api_key_for_models:
        require_valid_api_key(request)


def _presented_token(request: Request) -> str:
    """Извлекает токен клиента из Authorization: Bearer или X-API-Key."""
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token
    return request.headers.get("x-api-key", "").strip()


def require_valid_api_key(request: Request) -> None:
    """Проверяет ключ только для текущего класса маршрутов.

    Для /v1/* приоритетен OPENAI_API_KEY; при его отсутствии принимается
    API_KEY. Для панели и legacy /chat принимается только API_KEY.
    """
    settings = request.app.state.settings
    if request.url.path.startswith("/v1/"):
        accepted = [settings.openai_api_key or settings.api_key]
    else:
        accepted = [settings.api_key]
    accepted = [key for key in accepted if key]
    if not accepted:
        return

    presented = _presented_token(request)
    is_valid = bool(presented) and any(
        hmac.compare_digest(presented, key) for key in accepted
    )
    if is_valid:
        return

    if request.url.path.startswith("/v1/"):
        error = {
            "code": "invalid_api_key",
            "message": "Некорректный API-ключ.",
            "openai": True,
            "details": None,
        }
    else:
        error = {
            "code": "authentication_required",
            "message": "Требуется действительный API-ключ.",
            "details": None,
        }
    raise HTTPException(
        status_code=401,
        detail=error,
        headers={"WWW-Authenticate": "Bearer"},
    )


def redact_secrets(text: str, replacement: str = "[REDACTED]") -> str:
    """Заменяет похожие на секреты фрагменты на ``[REDACTED]``.

    Функция применяется ко всему, что потенциально уходит в лог:
    сообщениям об ошибках внешних библиотек, значениям заголовков и т.п.
    """
    if not text:
        return text
    result = text
    for name, pattern in _SECRET_PATTERNS:
        if name == "generic_assignment":
            # Сохраняем имя параметра, скрываем только значение.
            result = pattern.sub(lambda m: f"{m.group(1)}={replacement}", result)
        else:
            result = pattern.sub(replacement, result)
    return result


def _normalize_ip(raw: str) -> str | None:
    """Приводит строку к каноническому виду IP-адреса или возвращает None."""
    if not raw:
        return None
    candidate = raw.strip()
    # Убираем возможный порт вида "203.0.113.5:54321" или "[::1]:54321".
    if candidate.startswith("["):
        candidate = candidate.split("]", 1)[0].lstrip("[")
    elif candidate.count(":") == 1 and "." in candidate:
        candidate = candidate.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _is_trusted_proxy(peer_ip: str | None, trusted: tuple[str, ...]) -> bool:
    """Проверяет, входит ли прямой отправитель в список доверенных прокси."""
    if peer_ip is None:
        return False
    if peer_ip in trusted:
        return True
    try:
        peer = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    for entry in trusted:
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        if peer in network:
            return True
    return False


def get_client_identifier(request: Request, settings: Settings) -> str:
    """Возвращает ключ, по которому считается лимит запросов.

    По умолчанию используется IP-адрес прямого TCP-соединения
    (``request.client.host``), подделать который клиент не может.

    Заголовок ``X-Forwarded-For`` учитывается ТОЛЬКО если:
      * включён параметр ``TRUST_PROXY_HEADERS=true``, И
      * прямой отправитель входит в ``TRUSTED_PROXIES``.

    Без этих двух условий значение заголовка игнорируется: иначе любой
    клиент подставил бы чужой IP и обошёл лимит (или наоборот, «подставил»
    другого пользователя).
    """
    peer_raw = request.client.host if request.client else None
    peer_ip = _normalize_ip(peer_raw) if peer_raw else None

    if settings.trust_proxy_headers and _is_trusted_proxy(
        peer_ip, settings.trusted_proxy_list
    ):
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            # Берём крайний правый адрес: он добавлен нашим доверенным прокси,
            # а левые значения целиком контролируются клиентом.
            for candidate in reversed([p.strip() for p in forwarded.split(",")]):
                normalized = _normalize_ip(candidate)
                if normalized:
                    return f"xff:{normalized}"
        real_ip = request.headers.get("x-real-ip", "")
        normalized_real = _normalize_ip(real_ip)
        if normalized_real:
            return f"xff:{normalized_real}"

    if settings.trust_proxy_headers and not _is_trusted_proxy(
        peer_ip, settings.trusted_proxy_list
    ):
        # Один раз на запрос — на уровне DEBUG, чтобы не засорять логи.
        logger.debug(
            "TRUST_PROXY_HEADERS=true, но прямой клиент не входит в TRUSTED_PROXIES; "
            "заголовки X-Forwarded-For игнорируются"
        )

    return f"ip:{peer_ip or 'unknown'}"


class RateLimitViolationLog:
    """Кольцевой буфер последних нарушений лимита.

    Хранит только метаданные (время, идентификатор клиента, маршрут).
    Содержимое сообщений сюда не попадает, на диск ничего не пишется.
    Буфер нужен исключительно для наблюдаемости во время демонстрации.
    """

    def __init__(self, maxlen: int = 100) -> None:
        self._items: Deque[dict[str, str]] = deque(maxlen=max(0, maxlen))

    def add(self, client: str, route: str) -> None:
        """Регистрирует факт нарушения лимита."""
        if self._items.maxlen == 0:
            return
        self._items.append(
            {
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "client": redact_secrets(client),
                "route": route,
            }
        )

    def snapshot(self) -> list[dict[str, str]]:
        """Возвращает копию буфера (последние нарушения в конце)."""
        return list(self._items)

    def clear(self) -> None:
        """Очищает буфер (используется в тестах)."""
        self._items.clear()


def security_warnings(settings: Settings) -> list[str]:
    """Возвращает список предупреждений о небезопасной конфигурации."""
    warnings: list[str] = []

    if settings.is_public_bind:
        warnings.append(
            f"HOST={settings.host}: API слушает не только localhost. "
            "Убедитесь, что доступ ограничен межсетевым экраном и что сервис "
            "не опубликован в интернет."
        )
        if not settings.api_key:
            warnings.append(
                "Для сетевого режима не задан API_KEY: любой клиент из доступной "
                "сети может вызывать модель. Настройте сильный ключ."
            )

    if not settings.ollama_endpoint_is_local:
        warnings.append(
            f"OLLAMA_BASE_URL={settings.ollama_base_url}: Ollama не на loopback-адресе. "
            "Проверьте, что это доверенный узел вашей сети."
        )

    if settings.trust_proxy_headers and not settings.trusted_proxy_list:
        warnings.append(
            "TRUST_PROXY_HEADERS=true, но TRUSTED_PROXIES пуст: заголовки "
            "X-Forwarded-For учитываться не будут."
        )

    if settings.max_context_tokens + settings.max_output_tokens > 8192:
        warnings.append(
            "Большой бюджет контекста требует больше оперативной памяти; "
            "на слабом оборудовании генерация может замедлиться."
        )

    return warnings


def log_security_warnings(settings: Settings) -> None:
    """Пишет предупреждения о конфигурации в лог при старте приложения."""
    for warning in security_warnings(settings):
        logger.warning("Конфигурация: %s", redact_secrets(warning))
