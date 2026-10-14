#!/usr/bin/env python3
"""Сквозная проверка реального API и локальной генерации Ollama.

Команда не скачивает модели: она проверяет health, затем делает один
реальный POST /chat с многошаговой историей. Требуется заранее запустить
Ollama с установленной моделью и FastAPI-сервис.

Пример:
    python scripts/integration_check.py --url http://127.0.0.1:5002
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

import httpx


async def check(url: str, timeout: float) -> int:
    root = url.rstrip("/")
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=3.0)) as client:
        print(f"Проверяю API: {root}")
        try:
            live = await client.get(f"{root}/health/live")
            print(f"GET /health/live: HTTP {live.status_code} — {live.text[:300]}")
            if live.status_code != 200:
                return 1

            health = await client.get(f"{root}/health")
            print(f"GET /health: HTTP {health.status_code} — {health.text[:500]}")
            if health.status_code != 200:
                print("Проверьте, что Ollama запущена и модель установлена.")
                return 1

            payload = {
                "messages": [
                    {"role": "system", "content": "Отвечай по-русски кратко."},
                    {"role": "user", "content": "Запомни кодовое слово: кедр."},
                    {"role": "assistant", "content": "Запомнил: кедр."},
                    {"role": "user", "content": "Какое кодовое слово я назвал?"},
                ]
            }
            print("POST /chat: отправляю реальный запрос локальной модели…")
            started = time.perf_counter()
            response = await client.post(f"{root}/chat", json=payload)
            elapsed = time.perf_counter() - started
            print(f"POST /chat: HTTP {response.status_code}, {elapsed:.2f} с")
            try:
                data = response.json()
            except ValueError:
                print(response.text[:500])
                return 1
            if response.status_code == 200:
                print(f"Модель: {data.get('model')}")
                print(f"Ответ: {data.get('response')}")
                return 0
            print(f"Ошибка: {data.get('error', data)}")
            return 1
        except httpx.TimeoutException:
            print("Таймаут: API или генерация не ответили вовремя.", file=sys.stderr)
            return 1
        except httpx.HTTPError as exc:
            print(f"Не удалось подключиться: {type(exc).__name__}", file=sys.stderr)
            return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5002")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    return asyncio.run(check(args.url, args.timeout))


if __name__ == "__main__":
    raise SystemExit(main())
