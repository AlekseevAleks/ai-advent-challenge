"""Журнал запросов к модели с записью в JSON-файлы.

Каждая запись — отдельный JSONL-совместимый файл в каталоге
``REQUEST_LOG_DIR`` (по умолчанию ``logs/requests/``) с именем вида
``2026-10-14T05-46-09_ab12cd34.json``.

Что попадает в файл (по требованию владельца сервиса):

* метаданные запроса: время, клиент, модель, число сообщений, оценка токенов,
  длительность генерации, HTTP-статус, код ошибки;
* **полные тексты сообщений и ответа модели**.

Приватность: содержимое сохраняется в открытом виде на диск, поэтому каталог
добавлен в ``.gitignore``, запись можно выключить настройкой
``REQUEST_LOG_ENABLED=false``, а запись не выполняется, пока не передан запрос
к ``POST /chat``. Не храните в этом каталоге персональные данные без согласия
пользователей и не отправляйте его в публичные репозитории.

Запись файлов выполняется в отдельном потоке (``asyncio.to_thread``), чтобы
дисковая операция не блокировала event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque

logger = logging.getLogger("app.request_log")

# Сколько последних записей держать в памяти для страницы «Логи»
# (файлы хранят все записи, буфер нужен только для быстрого отображения).
DEFAULT_MAX_ENTRIES = 500

_SAFE_FILE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-[0-9]{2}_[0-9a-f]{8}\.json$")


@dataclass
class RequestLogRecord:
    """Одна запись журнала запроса к модели."""

    id: str
    started_at: str
    finished_at: str | None = None
    client: str = "unknown"
    model: str = ""
    ollama_base_url: str = ""
    status: str = "in_progress"  # ok | error | rejected
    http_status: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: float | None = None
    message_count: int = 0
    roles: list[str] = field(default_factory=list)
    estimated_input_tokens: int | None = None
    max_output_tokens: int | None = None
    num_ctx: int | None = None
    response_chars: int | None = None
    messages: list[dict[str, str]] = field(default_factory=list)
    response: str | None = None
    file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "client": self.client,
            "model": self.model,
            "ollama_base_url": self.ollama_base_url,
            "status": self.status,
            "http_status": self.http_status,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "duration_ms": self.duration_ms,
            "message_count": self.message_count,
            "roles": self.roles,
            "estimated_input_tokens": self.estimated_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "num_ctx": self.num_ctx,
            "response_chars": self.response_chars,
            "messages": self.messages,
            "response": self.response,
            "file": self.file,
        }

    def to_summary(self) -> dict[str, Any]:
        """Краткая версия для списка в панели (без текстов)."""
        return {
            "id": self.id,
            "started_at": self.started_at,
            "client": self.client,
            "model": self.model,
            "status": self.status,
            "http_status": self.http_status,
            "error_code": self.error_code,
            "duration_ms": self.duration_ms,
            "message_count": self.message_count,
            "estimated_input_tokens": self.estimated_input_tokens,
            "response_chars": self.response_chars,
            "file": self.file,
        }


class RequestLogStore:
    """Пишет записи в JSON-файлы и держит их краткий индекс в памяти."""

    def __init__(
        self,
        directory: Path,
        *,
        enabled: bool = True,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self.directory = Path(directory)
        self.enabled = enabled
        self.max_entries = max_entries
        self._recent: Deque[RequestLogRecord] = deque(maxlen=max_entries)
        self._lock = threading.Lock()
        self._file_lock = threading.Lock()
        self._write_errors = 0
        self.directory.mkdir(parents=True, exist_ok=True)
        self._load_recent_files()

    def _load_recent_files(self) -> None:
        """Восстанавливает индекс последних JSON-файлов после перезапуска."""
        allowed = set(RequestLogRecord.__dataclass_fields__)
        files = sorted(
            (
                path
                for path in self.directory.iterdir()
                if path.is_file()
                and not path.is_symlink()
                and _SAFE_FILE_RE.match(path.name)
            ),
            key=lambda path: path.stat().st_mtime,
        )
        restored: list[RequestLogRecord] = []
        for path in files[-self.max_entries :]:
            try:
                with path.open(encoding="utf-8") as handle:
                    raw = json.load(handle)
                if isinstance(raw, dict):
                    fields = {key: value for key, value in raw.items() if key in allowed}
                    record = RequestLogRecord(**fields)
                    record.file = path.name
                    restored.append(record)
            except (OSError, ValueError, TypeError):
                logger.warning("Пропущена повреждённая запись журнала")
        with self._lock:
            self._recent.extend(restored)

    def _prune_files(self) -> None:
        """Удаляет самые старые записи сверх настроенного retention-лимита."""
        files = sorted(
            (
                path
                for path in self.directory.iterdir()
                if path.is_file()
                and not path.is_symlink()
                and _SAFE_FILE_RE.match(path.name)
            ),
            key=lambda path: path.stat().st_mtime,
        )
        for path in files[: max(0, len(files) - self.max_entries)]:
            try:
                path.unlink()
            except OSError:
                logger.warning("Не удалось удалить старую запись журнала")

    # --------------------------- служебное ------------------------------

    def _file_name(self, record_id: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        return f"{stamp}_{record_id[:8]}.json"

    def _write_file(self, record: RequestLogRecord) -> str | None:
        """Синхронная запись файла (вызывается из отдельного потока)."""
        file_name = self._file_name(record.id)
        path = self.directory / file_name
        with self._file_lock:
            try:
                # atomic replace: панель никогда не прочитает недописанный файл
                temporary = path.with_suffix(".tmp")
                with open(temporary, "w", encoding="utf-8") as handle:
                    json.dump(record.to_dict(), handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
                self._prune_files()
                return file_name
            except OSError as exc:
                self._write_errors += 1
                logger.error("Не удалось записать файл журнала: %s", type(exc).__name__)
                return None

    async def flush(self, record: RequestLogRecord) -> RequestLogRecord:
        """Дописывает запись на диск и в индекс памяти."""
        if not self.enabled:
            return record
        record.file = await asyncio.to_thread(self._write_file, record)
        with self._lock:
            self._recent.append(record)
        return record

    # ----------------------------- API ----------------------------------

    def is_enabled(self) -> bool:
        return self.enabled

    def stats(self) -> dict[str, Any]:
        """Сводка по журналу для страницы логов."""
        entries = 0
        try:
            entries = sum(
                1
                for item in self.directory.iterdir()
                if item.is_file() and _SAFE_FILE_RE.match(item.name)
            )
        except OSError:
            entries = 0
        with self._lock:
            recent = list(self._recent)
        return {
            "enabled": self.enabled,
            "directory": str(self.directory),
            "files": entries,
            "buffered": len(recent),
            "max_entries": self.max_entries,
            "write_errors": self._write_errors,
        }

    def list_entries(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
        client: str | None = None,
        model: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        """Возвращает страницу журнала, новые записи — первыми."""
        with self._lock:
            items = list(self._recent)

        filtered = []
        for record in reversed(items):
            if status and record.status != status:
                continue
            if client and client not in record.client:
                continue
            if model and model not in record.model:
                continue
            if search and not self._matches(record, search):
                continue
            filtered.append(record)

        total = len(filtered)
        window = filtered[offset : offset + limit]
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [record.to_summary() for record in window],
        }

    @staticmethod
    def _matches(record: RequestLogRecord, needle: str) -> bool:
        needle = needle.lower()
        if needle in (record.error_code or "").lower():
            return True
        if needle in (record.error_message or "").lower():
            return True
        if needle in (record.response or "").lower():
            return True
        return any(needle in message.get("content", "").lower() for message in record.messages)

    def get_entry(self, record_id: str) -> RequestLogRecord | None:
        """Возвращает запись из буфера по идентификатору."""
        with self._lock:
            for record in self._recent:
                if record.id == record_id:
                    return record
        return None

    def get_from_file(self, file_name: str) -> dict[str, Any] | None:
        """Читает запись из файла; имя файла строго валидируется."""
        if not _SAFE_FILE_RE.match(file_name):
            return None
        path = self.directory / file_name
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None

    def read_sidecar_content(self, record_id: str) -> dict[str, Any] | None:
        """Совместимость: полный текст хранится в том же JSON-файле."""
        record = self.get_entry(record_id)
        if record is None:
            return None
        return {"messages": record.messages, "response": record.response}

    def clear(self) -> dict[str, Any]:
        """Удаляет все JSON-файлы и очищает буфер памяти."""
        deleted = 0
        with self._file_lock:
            for path in self.directory.iterdir():
                if path.is_file() and not path.is_symlink() and _SAFE_FILE_RE.match(path.name):
                    try:
                        path.unlink()
                        deleted += 1
                    except OSError:
                        logger.warning("Не удалось удалить запись журнала")
        with self._lock:
            self._recent.clear()
        return {**self.stats(), "deleted": deleted}


def new_record(
    *,
    client: str,
    settings_model: str,
    ollama_base_url: str,
    messages: list[dict[str, str]],
    estimated_input_tokens: int | None,
    max_output_tokens: int | None,
    num_ctx: int | None,
) -> RequestLogRecord:
    """Создаёт запись журнала в состоянии «выполняется»."""
    return RequestLogRecord(
        id=uuid.uuid4().hex,
        started_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        client=client,
        model=settings_model,
        ollama_base_url=ollama_base_url,
        status="in_progress",
        message_count=len(messages),
        roles=[message.get("role", "") for message in messages],
        estimated_input_tokens=estimated_input_tokens,
        max_output_tokens=max_output_tokens,
        num_ctx=num_ctx,
        messages=list(messages),
    )
