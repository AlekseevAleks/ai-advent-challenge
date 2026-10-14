#!/usr/bin/env python3
"""Пример AI-агента на официальном OpenAI SDK против локального сервиса.

Подключение идёт только к вашему localhost: внешние AI API не используются.

Установка клиентской библиотеки (не нужна серверу):

    pip install openai

Запуск (сервер уже работает на 127.0.0.1:5012):

    OPENAI_API_KEY=local-agent-key python scripts/openai_client_example.py
    python scripts/openai_client_example.py --no-stream

Переменные окружения:
    LOCAL_LLM_BASE_URL  — по умолчанию http://127.0.0.1:5012/v1
    LOCAL_LLM_MODEL     — по умолчанию local-llm
    OPENAI_API_KEY      — тот же ключ, что OPENAI_API_KEY в .env сервера
"""

from __future__ import annotations

import argparse
import os
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:5012/v1"),
        help="Base URL OpenAI-совместимого API (по умолчанию локальный сервис).",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("LOCAL_LLM_MODEL", "local-llm"),
        help="Имя модели, которое видит агент.",
    )
    parser.add_argument("--prompt", default="Привет! Ответь одним коротким предложением.")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Отключить потоковую генерацию.",
    )
    parser.add_argument(
        "--system",
        default=None,
        help="Необязательная system-инструкция для агента.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        from openai import OpenAI
    except ImportError:
        print(
            "Не установлен пакет openai. Выполните: pip install openai",
            file=sys.stderr,
        )
        return 2

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print(
            "Задайте OPENAI_API_KEY (значение из OPENAI_API_KEY в .env сервера). "
            "Если ключ на сервере не настроен, можно передать любое непустое значение.",
            file=sys.stderr,
        )
        return 2

    client = OpenAI(base_url=args.base_url, api_key=api_key, timeout=180.0)

    print(f"Модели, доступные агенту ({args.base_url}/models):")
    for model in client.models.list().data:
        print(f"  - {model.id} (owned_by={model.owned_by})")

    messages: list[dict[str, str]] = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": args.prompt})
    print(f"\nЗапрос к модели {args.model}: {args.prompt}")

    if args.no_stream:
        completion = client.chat.completions.create(
            model=args.model,
            messages=messages,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        choice = completion.choices[0]
        print(f"\nОтвет (finish_reason={choice.finish_reason}):\n{choice.message.content}")
        if completion.usage is not None:
            print(
                f"\nТокены: prompt={completion.usage.prompt_tokens}, "
                f"completion={completion.usage.completion_tokens}, "
                f"total={completion.usage.total_tokens}"
            )
        else:
            print("\nusage не возвращён: Ollama не сообщила счётчики токенов.")
        return 0

    print("\nОтвет (поток):")
    stream = client.chat.completions.create(
        model=args.model,
        messages=messages,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        stream=True,
    )
    finish_reason = None
    for chunk in stream:
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        if choice.delta.content:
            print(choice.delta.content, end="", flush=True)
        if choice.finish_reason:
            finish_reason = choice.finish_reason
    print(f"\n\nfinish_reason={finish_reason}")
    print("В потоковом режиме usage не отправляется — это соответствует OpenAI API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
