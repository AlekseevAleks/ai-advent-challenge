#!/usr/bin/env python3
"""Нагрузочный тест реальной генерации через POST /chat.

По умолчанию отправляет 5 запросов к локальному API, последовательно.
Параметр ``--mode parallel`` запускает заданное количество запросов
с ограниченным уровнем параллелизма. Запросы обращаются к /chat, а не /health.

Примеры:
    python scripts/load_test.py
    python scripts/load_test.py --requests 5 --concurrency 5 --mode parallel
    python scripts/load_test.py --requests 10 --concurrency 2 --mode parallel --report reports/run.json

Результаты зависят от модели, RAM/VRAM, версии Ollama и настроек параллельности.
Скрипт не предполагает, что генерация будет происходить одновременно.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


@dataclass
class Result:
    """Результат одного запроса."""

    request_id: int
    status_code: int | None
    elapsed_seconds: float
    success: bool
    response_chars: int
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Нагрузочная проверка локального LLM API через реальную генерацию."
    )
    parser.add_argument("--url", default="http://127.0.0.1:5002", help="Корневой URL API")
    parser.add_argument("--requests", type=int, default=5, help="Количество POST /chat запросов")
    parser.add_argument("--concurrency", type=int, default=1, help="Максимум одновременных HTTP запросов")
    parser.add_argument(
        "--mode",
        choices=("sequential", "parallel"),
        default="sequential",
        help="sequential — строго по одному запросу; parallel — одновременно до --concurrency",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="Таймаут одного запроса, секунд (локальная генерация может быть долгой)",
    )
    parser.add_argument(
        "--prompt",
        default="Ответь одной короткой фразой: проверка генерации работает.",
        help="Промпт для каждого тестового запроса",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Опционально сохранить полный JSON-отчёт в файл",
    )
    args = parser.parse_args()
    if args.requests < 1:
        parser.error("--requests должен быть не меньше 1")
    if args.concurrency < 1:
        parser.error("--concurrency должен быть не меньше 1")
    if args.timeout <= 0:
        parser.error("--timeout должен быть больше 0")
    return args


async def run(args: argparse.Namespace) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(args.concurrency)
    url = args.url.rstrip("/") + "/chat"
    timeout = httpx.Timeout(args.timeout, connect=5.0)
    results: list[Result] = []

    async with httpx.AsyncClient(timeout=timeout) as client:
        async def one_request(request_id: int) -> Result:
            if args.mode == "parallel":
                await semaphore.acquire()
            started = time.perf_counter()
            try:
                response = await client.post(
                    url,
                    json={"messages": [{"role": "user", "content": args.prompt}]},
                )
                elapsed = time.perf_counter() - started
                success = response.status_code == 200
                response_chars = 0
                error = None
                try:
                    data = response.json()
                    if success:
                        response_chars = len(data.get("response", ""))
                    else:
                        error = data.get("error", {}).get("message", response.text[:200])
                except (ValueError, AttributeError):
                    error = response.text[:200]
                return Result(
                    request_id=request_id,
                    status_code=response.status_code,
                    elapsed_seconds=elapsed,
                    success=success,
                    response_chars=response_chars,
                    error=error,
                )
            except (httpx.HTTPError, asyncio.TimeoutError) as exc:
                elapsed = time.perf_counter() - started
                return Result(
                    request_id=request_id,
                    status_code=None,
                    elapsed_seconds=elapsed,
                    success=False,
                    response_chars=0,
                    error=type(exc).__name__,
                )
            finally:
                if args.mode == "parallel":
                    semaphore.release()

        overall_start = time.perf_counter()
        if args.mode == "sequential":
            for request_id in range(1, args.requests + 1):
                result = await one_request(request_id)
                results.append(result)
                print_result(result)
        else:
            tasks = [one_request(i) for i in range(1, args.requests + 1)]
            results = await asyncio.gather(*tasks)
            for result in sorted(results, key=lambda item: item.request_id):
                print_result(result)
        total_elapsed = time.perf_counter() - overall_start

    successful = sum(result.success for result in results)
    errors = len(results) - successful
    durations = [result.elapsed_seconds for result in results]
    average = statistics.mean(durations) if durations else 0.0
    report: dict[str, Any] = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "url": url,
        "mode": args.mode,
        "requests": args.requests,
        "concurrency": 1 if args.mode == "sequential" else args.concurrency,
        "successful": successful,
        "errors": errors,
        "total_elapsed_seconds": round(total_elapsed, 3),
        "average_response_seconds": round(average, 3),
        "results": [asdict(result) for result in results],
    }
    print("\n--- Итог ---")
    print(f"Режим:                    {args.mode}")
    print(f"Запросов:                 {args.requests}")
    print(f"Параллелизм:              {report['concurrency']}")
    print(f"Успешно:                  {successful}")
    print(f"Ошибок:                   {errors}")
    print(f"Общее время:              {total_elapsed:.3f} с")
    print(f"Среднее время ответа:     {average:.3f} с")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"JSON-отчёт:               {args.report}")

    return report


def print_result(result: Result) -> None:
    status = str(result.status_code) if result.status_code is not None else "NETWORK"
    outcome = "OK" if result.success else "ERROR"
    line = (
        f"#{result.request_id:02d} {outcome:5s} HTTP {status:>7s} "
        f"{result.elapsed_seconds:8.3f} с"
    )
    if result.success:
        line += f" | ответ: {result.response_chars} символов"
    elif result.error:
        line += f" | {result.error[:180]}"
    print(line)


def main() -> int:
    args = parse_args()
    try:
        report = asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nТест остановлен пользователем.", file=sys.stderr)
        return 130
    return 0 if report["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
