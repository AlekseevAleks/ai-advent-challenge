#!/usr/bin/env python3
"""Local chat site: serves the UI and proxies prompts to OpenAI."""

from __future__ import annotations

import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
KEY_FILE = ROOT / "api-key.txt"
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")
SYSTEM_PROMPT = "Ты полезный ассистент. Отвечай кратко и по делу."
TEMPERATURE = 0.7
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
HIDDEN_FILES = {"api-key.txt"}
MODEL_SETTINGS = {
    "model": MODEL,
    "temperature": TEMPERATURE,
    "system_prompt": SYSTEM_PROMPT,
    "endpoint": OPENAI_URL,
}


def load_api_key() -> str:
    if not KEY_FILE.is_file():
        raise FileNotFoundError("Файл api-key.txt не найден.")
    key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key or key.startswith("sk-REPLACE"):
        raise ValueError("Положите настоящий ключ OpenAI в api-key.txt.")
    return key


def usage_info(data: dict) -> dict:
    usage = data.get("usage") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    completion_details = usage.get("completion_tokens_details") or {}
    info = {
        "prompt": usage.get("prompt_tokens"),
        "completion": usage.get("completion_tokens"),
        "total": usage.get("total_tokens"),
    }
    if "cached_tokens" in prompt_details:
        info["cached"] = prompt_details["cached_tokens"]
    if "reasoning_tokens" in completion_details:
        info["reasoning"] = completion_details["reasoning_tokens"]
    return info


def ask_openai(prompt: str) -> tuple[str, dict]:
    payload = json.dumps(
        {
            "model": MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": TEMPERATURE,
        }
    ).encode("utf-8")

    request = Request(
        OPENAI_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {load_api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(body)["error"]["message"]
        except (KeyError, json.JSONDecodeError, TypeError):
            message = body or str(error)
        raise RuntimeError(f"OpenAI: {message}") from error
    except URLError as error:
        raise RuntimeError(f"Не удалось связаться с OpenAI: {error.reason}") from error

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenAI вернул пустой ответ.")
    content = choices[0].get("message", {}).get("content")
    if not content:
        raise RuntimeError("В ответе OpenAI нет текста.")
    return content.strip(), usage_info(data)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}")

    def do_GET(self):
        name = Path(self.path.split("?", 1)[0]).name
        if name in HIDDEN_FILES:
            self.send_error(404, "Not found")
            return
        if self.path in {"/", "/index.html"}:
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/chat":
            self.send_error(404, "Not found")
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
            prompt = str(body.get("prompt", "")).strip()
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "Некорректный JSON."})
            return

        if not prompt:
            self._json(400, {"error": "Введите текст запроса."})
            return

        try:
            answer, usage = ask_openai(prompt)
        except (FileNotFoundError, ValueError, RuntimeError) as error:
            self._json(502, {"error": str(error)})
            return

        self._json(
            200,
            {
                "reply": answer,
                "model": MODEL,
                "usage": usage,
                "settings": MODEL_SETTINGS,
            },
        )

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Сайт: http://127.0.0.1:{port}")
    print(f"Модель: {MODEL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
