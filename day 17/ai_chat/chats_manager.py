"""Работа с локальным файлом чатов chats.json.

Хранит список чатов и их сообщения, обеспечивает создание, чтение,
удаление и добавление сообщений. Все операции защищены блокировкой,
чтобы избежать гонок при параллельных запросах.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHATS_PATH = os.path.join(BASE_DIR, "chats.json")

_lock = threading.RLock()


def _now() -> str:
    """Текущее время в формате ISO-8601 (UTC)."""
    return datetime.now(timezone.utc).isoformat()


def _ensure_file() -> None:
    """Создаёт chats.json с пустой структурой, если файла нет."""
    if not os.path.exists(CHATS_PATH):
        with open(CHATS_PATH, "w", encoding="utf-8") as fh:
            json.dump({"chats": []}, fh, ensure_ascii=False, indent=2)


def _read() -> Dict[str, Any]:
    """Читает файл чатов, возвращая корректную структуру даже при повреждении."""
    _ensure_file()
    try:
        with open(CHATS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        data = {"chats": []}
    if not isinstance(data, dict) or not isinstance(data.get("chats"), list):
        data = {"chats": []}
    return data


def _write(data: Dict[str, Any]) -> None:
    """Атомарно записывает данные чатов на диск."""
    tmp_path = CHATS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp_path, CHATS_PATH)


def list_chats() -> List[Dict[str, Any]]:
    """Возвращает список чатов без сообщений, отсортированный по дате создания."""
    with _lock:
        chats = _read()["chats"]
        result = [
            {
                "id": chat.get("id"),
                "title": chat.get("title", "Новый чат"),
                "model": chat.get("model", ""),
                "created_at": chat.get("created_at", ""),
                "message_count": len(chat.get("messages", [])),
            }
            for chat in chats
        ]
        result.sort(key=lambda c: c.get("created_at", ""), reverse=True)
        return result


def get_chat(chat_id: str) -> Optional[Dict[str, Any]]:
    """Возвращает чат по идентификатору или ``None``, если он не найден."""
    with _lock:
        for chat in _read()["chats"]:
            if chat.get("id") == chat_id:
                return chat
        return None


def create_chat(model: str, title: str = "Новый чат") -> Dict[str, Any]:
    """Создаёт новый чат с указанной моделью и сохраняет его на диск."""
    with _lock:
        data = _read()
        chat = {
            "id": str(uuid.uuid4()),
            "title": title or "Новый чат",
            "model": model,
            "created_at": _now(),
            "messages": [],
        }
        data["chats"].append(chat)
        _write(data)
        return chat


def delete_chat(chat_id: str) -> bool:
    """Удаляет чат по идентификатору. Возвращает ``True``, если чат был удалён."""
    with _lock:
        data = _read()
        before = len(data["chats"])
        data["chats"] = [c for c in data["chats"] if c.get("id") != chat_id]
        if len(data["chats"]) == before:
            return False
        _write(data)
        return True


def _normalize_usage(usage: Dict[str, Any]) -> Dict[str, Any]:
    """Приводит статистику токенов к единому виду, сохраняя ``cost_rub``."""
    normalized: Dict[str, Any] = {
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }
    cost_rub = usage.get("cost_rub")
    if cost_rub is not None:
        try:
            normalized["cost_rub"] = float(cost_rub)
        except (TypeError, ValueError):
            pass
    return normalized


def add_message(
    chat_id: str,
    role: str,
    content: str,
    usage: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Добавляет сообщение в чат и сохраняет файл. Возвращает добавленное сообщение.

    Для ответов ассистента можно передать ``usage`` со статистикой токенов
    (``prompt_tokens``, ``completion_tokens``, ``total_tokens``) и стоимостью
    ``cost_rub``. Параметр ``request_id`` связывает сообщение с логом запроса
    к внешнему API.
    """
    with _lock:
        data = _read()
        for chat in data["chats"]:
            if chat.get("id") == chat_id:
                message: Dict[str, Any] = {"role": role, "content": content}
                if usage:
                    message["usage"] = _normalize_usage(usage)
                if request_id:
                    message["request_id"] = request_id
                chat.setdefault("messages", []).append(message)
                _write(data)
                return message
        return None


def update_message(chat_id: str, index: int, content: str) -> bool:
    """Обновляет содержимое сообщения по индексу (используется для стрима)."""
    with _lock:
        data = _read()
        for chat in data["chats"]:
            if chat.get("id") == chat_id:
                messages = chat.get("messages", [])
                if 0 <= index < len(messages):
                    messages[index]["content"] = content
                    _write(data)
                    return True
        return False


def set_message_usage(chat_id: str, index: int, usage: Dict[str, Any]) -> bool:
    """Записывает статистику токенов в существующее сообщение по индексу.

    Используется, чтобы сохранить количество токенов запроса в сообщении
    пользователя после завершения стрима — тогда данные переживают
    перезапуск сервиса.
    """
    with _lock:
        data = _read()
        for chat in data["chats"]:
            if chat.get("id") == chat_id:
                messages = chat.get("messages", [])
                if 0 <= index < len(messages):
                    messages[index]["usage"] = _normalize_usage(usage)
                    _write(data)
                    return True
        return False


def set_title(chat_id: str, title: str) -> bool:
    """Устанавливает заголовок чата."""
    with _lock:
        data = _read()
        for chat in data["chats"]:
            if chat.get("id") == chat_id:
                chat["title"] = title
                _write(data)
                return True
        return False


def clear_messages(chat_id: str) -> bool:
    """Очищает историю сообщений чата, сохраняя сам чат."""
    with _lock:
        data = _read()
        for chat in data["chats"]:
            if chat.get("id") == chat_id:
                chat["messages"] = []
                _write(data)
                return True
        return False


def auto_title(text: str, limit: int = 30) -> str:
    """Формирует заголовок чата из первого сообщения пользователя."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return "Новый чат"
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "…"


def chat_usage(chat: Dict[str, Any]) -> Dict[str, Any]:
    """Считает суммарную статистику токенов и стоимость по всем сообщениям чата.

    Возвращает словарь с ключами ``prompt_tokens``, ``completion_tokens``,
    ``total_tokens`` и ``cost_rub``. Сообщения без данных о токенах
    игнорируются.
    """
    prompt = 0
    completion = 0
    total = 0
    cost_rub = 0.0
    has_cost = False
    for message in chat.get("messages", []):
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        prompt += int(usage.get("prompt_tokens", 0) or 0)
        completion += int(usage.get("completion_tokens", 0) or 0)
        total += int(usage.get("total_tokens", 0) or 0)
        message_cost = usage.get("cost_rub")
        if message_cost is not None:
            try:
                cost_rub += float(message_cost)
                has_cost = True
            except (TypeError, ValueError):
                pass
    result: Dict[str, Any] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }
    if has_cost:
        result["cost_rub"] = cost_rub
    return result
