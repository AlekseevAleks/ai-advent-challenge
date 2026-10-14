#!/usr/bin/env python3
"""Демонстрация 413 Max Context и HTTP 429 без вызова модели.

Скрипт отправляет MAX rate-limit + 1 заведомо слишком большой, но валидный
по JSON запрос. Первые обращения должны завершаться 413 на проверке контекста;
запрос сверх лимита должен получить 429. Перед демонстрацией перезапустите
однопроцессный API, чтобы очистить локальный счётчик, и запускайте скрипт
один раз в рамках окна rate limit.

Важно: этот тест намеренно потребляет весь лимит IP-клиента на текущее окно.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5002")
    parser.add_argument(
        "--requests",
        type=int,
        default=None,
        help="Количество запросов; по умолчанию RATE_LIMIT + 1 из .env.",
    )
    args = parser.parse_args()
    if args.requests is None:
        args.requests = get_settings().rate_limit_amount + 1
    if args.requests < 2:
        parser.error("Для проверки rate limit нужно хотя бы 2 запроса")
    return args


async def run(url: str, requests_count: int) -> int:
    root = url.rstrip("/")
    endpoint = f"{root}/chat"
    settings = get_settings()
    required_messages = max(
        1,
        (settings.context_token_budget + settings.max_message_chars + 3)
        // (settings.max_message_chars + 4),
    )
    message_count = min(
        settings.max_history_messages,
        max(3, required_messages),
    )
    estimated = message_count * (settings.max_message_chars + 4)
    if estimated <= settings.context_token_budget:
        print(
            "Текущая комбинация MAX_CONTEXT_TOKENS, MAX_MESSAGE_CHARS и "
            "MAX_HISTORY_MESSAGES не позволяет создать допустимую по отдельным "
            "лимитам историю, превышающую контекст. Уменьшите один из контекстных "
            "лимитов для демонстрации.",
            file=sys.stderr,
        )
        return 2

    messages = []
    for index in range(message_count):
        if index == 0 and message_count > 1:
            role = "system"
        elif index == message_count - 1:
            role = "user"
        elif index % 2 == 1:
            role = "assistant"
        else:
            role = "user"
        messages.append(
            {"role": role, "content": "x" * settings.max_message_chars}
        )
    payload = {"messages": messages}
    counts: dict[int, int] = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=3)) as client:
        for index in range(1, requests_count + 1):
            try:
                response = await client.post(endpoint, json=payload)
            except httpx.HTTPError as exc:
                print(f"#{index}: ошибка соединения: {type(exc).__name__}", file=sys.stderr)
                return 1
            counts[response.status_code] = counts.get(response.status_code, 0) + 1
            try:
                body = response.json()
                error = body.get("error", {})
                code = error.get("code", "")
                print(f"#{index}: HTTP {response.status_code} code={code}")
                if response.status_code == 413:
                    print(f"    {error.get('message', '')}")
                elif response.status_code == 429:
                    print(
                        f"    {error.get('message', '')}; "
                        f"Retry-After={response.headers.get('Retry-After', 'не задан')}"
                    )
            except (ValueError, AttributeError):
                print(f"#{index}: HTTP {response.status_code}; ответ не JSON")

    print("Итоговые статусы:", json.dumps(counts, ensure_ascii=False, sort_keys=True))
    if counts.get(429, 0) and counts.get(413, 0):
        print("Проверка пройдена: контекст отклоняется до генерации, лимит возвращает 429.")
        return 0
    print(
        "Не получены оба ожидаемых статуса. Проверьте RATE_LIMIT, лимиты контекста, "
        "IP-клиента и перезапустите API перед повтором."
    )
    return 1


def main() -> int:
    args = parse_args()
    return asyncio.run(run(args.url, args.requests))


if __name__ == "__main__":
    raise SystemExit(main())
