"""Настройки сервиса: читает url и api-ключ из файла api_key.txt."""

from dataclasses import dataclass
from pathlib import Path

API_KEY_FILE = Path("api_key.txt")
DATABASE_FILE = Path("agents.db")
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    api_key: str
    model: str = DEFAULT_MODEL
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


def load_config(path: Path = API_KEY_FILE) -> LlmConfig:
    """Читает файл: первая строка - url, вторая - api-ключ."""
    lines = _read_non_empty_lines(path)

    if len(lines) < 2:
        raise SystemExit(
            f"Файл {path} заполнен неправильно. Нужны две строки: "
            "первая - url (например https://api.openai.com/v1), "
            "вторая - api-ключ."
        )

    base_url, api_key = lines[0], lines[1]
    if not _looks_like_url(base_url):
        raise SystemExit(f"Первая строка в {path} должна быть url, сейчас: {base_url}")

    return LlmConfig(base_url=base_url, api_key=api_key)


def _read_non_empty_lines(path: Path) -> list[str]:
    if not path.exists():
        raise SystemExit(f"Не найден файл {path}. Создайте его рядом с app.py.")

    with path.open(encoding="utf-8") as file:
        return [line.strip() for line in file if line.strip()]


def _looks_like_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")
